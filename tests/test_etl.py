"""Тесты ETL: очистка (unit), идемпотентная загрузка и запуск из командной строки."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.core.database import Base, create_db_engine, create_session_factory
from app.etl import import_data
from app.etl.import_data import (
    EtlError,
    extract,
    run_import,
    transform,
    validate_and_clean,
)
from app.models import Examination, Patient
from app.services.model_service import ModelService
from tests.conftest import make_dataset

GOOD = {
    "id": "1", "age": "18393", "gender": "2", "height": "168", "weight": "62.5", "ap_hi": "110",
    "ap_lo": "80", "cholesterol": "1", "gluc": "1", "smoke": "0", "alco": "0", "active": "1",
}  # fmt: skip


def raw_frame(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows), dtype=str)


def reasons(rejected: pd.DataFrame) -> list:
    return rejected["reject_reason"].tolist()


# --- Очистка (unit) ---------------------------------------------------------


def test_clean_accepts_valid_row_and_keeps_fractional_weight():
    clean, rejected = validate_and_clean(raw_frame(GOOD))

    assert rejected.empty
    assert clean.loc[0, "weight"] == 62.5
    assert clean["id"].dtype.kind == "i"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"ap_hi": ""}, "missing_value"),
        ({"ap_hi": None}, "missing_value"),
        ({"weight": "много"}, "invalid_format"),
        ({"cholesterol": "1.5"}, "invalid_format"),
        ({"ap_hi": "16020"}, "out_of_range"),
        ({"ap_lo": "-70"}, "out_of_range"),
        ({"height": "55"}, "out_of_range"),
        ({"age": "3650"}, "out_of_range"),  # 10 лет — модель только для взрослых
        ({"cholesterol": "4"}, "out_of_range"),
        ({"smoke": "2"}, "out_of_range"),
        ({"gender": "3"}, "out_of_range"),
        ({"ap_hi": "90", "ap_lo": "120"}, "diastolic_above_systolic"),
    ],
)
def test_clean_rejects_with_reason(override, reason):
    clean, rejected = validate_and_clean(raw_frame({**GOOD, **override}))

    assert clean.empty
    assert reasons(rejected) == [reason]


def test_clean_rejects_duplicates_and_keeps_first():
    rows = [
        GOOD,
        {**GOOD},  # тот же id
        {**GOOD, "id": "2"},  # те же данные под другим id
        {**GOOD, "id": "3", "ap_hi": "120"},  # реально другая запись
    ]

    clean, rejected = validate_and_clean(raw_frame(*rows))

    assert clean["id"].tolist() == [1, 3]
    assert reasons(rejected) == ["duplicate_id", "duplicate_record"]


def test_clean_reports_only_the_first_reason_per_row():
    _, rejected = validate_and_clean(raw_frame({**GOOD, "ap_hi": "", "height": "55"}))

    assert reasons(rejected) == ["missing_value"]


def test_transform_maps_to_patient_and_examination_tables():
    clean, _ = validate_and_clean(raw_frame(GOOD, {**GOOD, "id": "2", "gender": "1", "smoke": "1", "ap_hi": "120"}))

    patients, examinations = transform(clean, date(2020, 1, 1))

    assert patients["gender"].tolist() == ["M", "F"]
    assert patients.loc[0, "birth_date"] == date(2020, 1, 1) - pd.Timedelta(days=18393)
    assert patients.loc[0, "full_name"] == "Пациент №1"
    assert examinations["smoke"].tolist() == [False, True]


# --- Extract ----------------------------------------------------------------


def test_extract_fails_clearly_for_missing_file_and_columns(tmp_path):
    with pytest.raises(EtlError, match="не найден"):
        extract(tmp_path / "nope.csv")

    broken = tmp_path / "broken.csv"
    broken.write_text("id;age\n1;100\n", encoding="utf-8")
    with pytest.raises(EtlError, match="height"):
        extract(broken)


def test_extract_respects_limit_and_delimiter(tmp_path):
    path = tmp_path / "data.csv"
    make_dataset(n_rows=50).to_csv(path, sep=";", index=False)

    assert len(extract(path, limit=10)) == 10
    path.write_text(path.read_text(encoding="utf-8").replace(";", ","), encoding="utf-8")
    assert len(extract(path)) == 50


# --- Загрузка в БД ----------------------------------------------------------


@pytest.fixture
def session_factory(app):
    return app.state.session_factory


@pytest.fixture
def source(tmp_path) -> Path:
    path = tmp_path / "cardio.csv"
    dataset = make_dataset(n_rows=120, seed=5)
    dirty = pd.concat(
        [
            dataset,
            dataset.head(1).assign(id=9001, ap_hi=16020),  # выброс
            dataset.head(1).assign(id=9002, weight=None),  # пропуск
            dataset.iloc[[2]].assign(id=9003),  # дубликат содержимого
        ]
    )
    dirty.to_csv(path, sep=";", index=False)
    return path


def count(session_factory, model) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_import_loads_valid_rows_and_reports_rejects(session_factory, source):
    report = run_import(session_factory, source, batch_size=50)

    assert report.rows_read == 123
    assert report.rejected == {"out_of_range": 1, "missing_value": 1, "duplicate_record": 1}
    assert (report.loaded, report.skipped_existing, report.scored) == (120, 0, 0)
    assert count(session_factory, Patient) == count(session_factory, Examination) == 120
    assert "загружено 120" in report.summary()


def test_import_is_idempotent(session_factory, source):
    first = run_import(session_factory, source, batch_size=50)
    second = run_import(session_factory, source, batch_size=50)

    assert second.loaded == 0
    assert second.skipped_existing == first.loaded
    assert count(session_factory, Patient) == 120
    assert count(session_factory, Examination) == 120


def test_import_resumes_after_partial_load(session_factory, source):
    run_import(session_factory, source, limit=40)

    report = run_import(session_factory, source)

    assert (report.skipped_existing, report.loaded) == (40, 80)
    assert count(session_factory, Patient) == 120


def test_import_stores_converted_values(session_factory, source):
    run_import(session_factory, source, measured_on=date(2024, 6, 1))

    with session_factory() as session:
        patient = session.scalar(select(Patient).where(Patient.external_id == 0))
        exam = session.scalar(select(Examination).where(Examination.patient_id == patient.id))

    assert patient.gender in {"F", "M"}
    assert patient.phone is None
    assert exam.measured_at.date() == date(2024, 6, 1)
    assert exam.risk_probability is None
    assert isinstance(exam.smoke, bool)


def test_import_with_model_scores_every_examination(session_factory, source, settings, model_bytes):
    settings.model_path.write_bytes(model_bytes)
    model_service = ModelService(settings.model_path)
    assert model_service.load_from_disk()

    report = run_import(session_factory, source, model_service=model_service, settings=settings)

    with session_factory() as session:
        levels = set(session.scalars(select(Examination.risk_level)))
        unscored = session.scalar(select(func.count()).where(Examination.risk_probability.is_(None)))
    assert report.scored == 120
    assert levels <= {"low", "medium", "high"}
    assert unscored == 0


def test_import_saves_rejected_rows_with_reasons(session_factory, source, tmp_path):
    rejected_path = tmp_path / "rejected.csv"

    run_import(session_factory, source, rejected_out=rejected_path)

    rejected = pd.read_csv(rejected_path)
    assert sorted(rejected["reject_reason"]) == ["duplicate_record", "missing_value", "out_of_range"]


# --- Командная строка -------------------------------------------------------


@pytest.fixture
def file_db(tmp_path) -> str:
    url = f"sqlite:///{tmp_path / 'etl.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


def test_cli_imports_and_prints_summary(file_db, source, capsys, monkeypatch):
    monkeypatch.setenv("MODEL_PATH", str(source.parent / "missing.pkl"))

    code = import_data.main(["--source", str(source), "--database-url", file_db])

    assert code == 0
    assert "загружено 120" in capsys.readouterr().out
    engine = create_db_engine(file_db)
    assert create_session_factory(engine)().scalar(select(func.count()).select_from(Patient)) == 120


def test_cli_fails_with_exit_code_for_missing_source(file_db, tmp_path):
    assert import_data.main(["--source", str(tmp_path / "absent.csv"), "--database-url", file_db]) == 1


def test_cli_score_without_model_fails(file_db, source, monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "missing.pkl"))

    assert import_data.main(["--source", str(source), "--database-url", file_db, "--score"]) == 2
