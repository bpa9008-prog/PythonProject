"""ETL: импорт пациентов и медосмотров из cardio_train.csv в БД.

Этапы: extract (чтение) → validate/clean (проверка и очистка) → transform (приведение к моделям БД) → load.

Запуск:
    python -m app.etl.import_data --source data/raw/cardio_train.csv [--limit 5000] [--score]

Идемпотентность: пациент однозначно определяется полем patients.external_id (колонка id датасета).
Уже загруженные записи пропускаются, поэтому повторный запуск ничего не дублирует.
"""

import argparse
import logging
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database import create_db_engine, create_session_factory
from app.models import Examination, Patient
from app.services import risk_service
from app.services.model_service import ModelService
from ml.preprocessing import VALID_RANGES

logger = logging.getLogger("app.etl")

ID_COLUMN = "id"
FEATURE_COLUMNS = [
    "age",
    "gender",
    "height",
    "weight",
    "ap_hi",
    "ap_lo",
    "cholesterol",
    "gluc",
    "smoke",
    "alco",
    "active",
]
REQUIRED_COLUMNS = [ID_COLUMN, *FEATURE_COLUMNS]
# Рост и вес могут быть дробными (65.5 кг); остальные колонки — только целые.
FRACTIONAL_COLUMNS = ["height", "weight"]
INTEGER_COLUMNS = [column for column in REQUIRED_COLUMNS if column not in FRACTIONAL_COLUMNS]
MIN_AGE_YEARS, MAX_AGE_YEARS = 18, 120
DEFAULT_MEASURED_ON = date(2020, 1, 1)
DEFAULT_BATCH_SIZE = 5000
GENDER_LETTERS = {1: "F", 2: "M"}

REJECT_MISSING = "missing_value"
REJECT_FORMAT = "invalid_format"
REJECT_RANGE = "out_of_range"
REJECT_PRESSURE = "diastolic_above_systolic"
REJECT_DUPLICATE_ID = "duplicate_id"
REJECT_DUPLICATE_RECORD = "duplicate_record"


class EtlError(Exception):
    """Ошибка, из-за которой импорт невозможен целиком (нет файла, нет колонок)."""


@dataclass
class EtlReport:
    rows_read: int = 0
    rejected: Counter = field(default_factory=Counter)
    loaded: int = 0
    skipped_existing: int = 0
    scored: int = 0
    seconds: float = 0.0

    @property
    def rows_rejected(self) -> int:
        return sum(self.rejected.values())

    def summary(self) -> str:
        reasons = ", ".join(f"{reason}={count}" for reason, count in sorted(self.rejected.items())) or "нет"
        return (
            f"прочитано {self.rows_read}, отклонено {self.rows_rejected} ({reasons}), "
            f"загружено {self.loaded}, уже было в БД {self.skipped_existing}, "
            f"оценено моделью {self.scored}, время {self.seconds:.1f} с"
        )


# --- Extract ----------------------------------------------------------------


def extract(source: Path, limit: int | None = None) -> pd.DataFrame:
    """Читает CSV как строки: типы проверяются на этапе очистки, чтобы мусор не ронял импорт."""
    if not source.exists():
        raise EtlError(f"Файл не найден: {source}")
    # sep=None — автоопределение разделителя: в датасете «;».
    df = pd.read_csv(source, sep=None, engine="python", dtype=str, nrows=limit)
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise EtlError(f"В файле нет обязательных колонок: {missing}")
    return df[REQUIRED_COLUMNS].copy()


# --- Validate / clean -------------------------------------------------------


def validate_and_clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Возвращает (чистые строки с числовыми типами, отклонённые строки с колонкой reject_reason).

    Каждая отклонённая строка получает первую подходящую причину.
    """
    text = raw.apply(lambda column: column.str.strip())
    blank = text.isna() | (text == "")
    numbers = text.apply(pd.to_numeric, errors="coerce")
    reason = pd.Series(pd.NA, index=raw.index, dtype="object")

    def reject(mask: pd.Series, name: str) -> None:
        reason[mask & reason.isna()] = name

    reject(blank.any(axis=1), REJECT_MISSING)
    reject(numbers.isna().any(axis=1), REJECT_FORMAT)

    # Дробное значение в целочисленной колонке (12.5 в id или cholesterol) — тоже неверный формат.
    reject((numbers[INTEGER_COLUMNS].fillna(0) % 1 != 0).any(axis=1), REJECT_FORMAT)

    age_years = numbers["age"] / risk_service.DAYS_IN_YEAR
    out_of_range = ~age_years.between(MIN_AGE_YEARS, MAX_AGE_YEARS)
    for column, (low, high) in VALID_RANGES.items():
        out_of_range |= ~numbers[column].between(low, high)
    out_of_range |= ~numbers["gender"].isin(GENDER_LETTERS)
    out_of_range |= ~numbers["cholesterol"].isin([1, 2, 3]) | ~numbers["gluc"].isin([1, 2, 3])
    for flag in ("smoke", "alco", "active"):
        out_of_range |= ~numbers[flag].isin([0, 1])
    reject(out_of_range, REJECT_RANGE)

    reject(numbers["ap_lo"] > numbers["ap_hi"], REJECT_PRESSURE)

    # Дубликаты ищем среди валидных строк; из каждой группы остаётся первая.
    # Сначала повторы id, затем повторы содержимого (одинаковые данные под разными id, как в cardio_train).
    valid = reason.isna()
    reject(valid & numbers[ID_COLUMN].duplicated(), REJECT_DUPLICATE_ID)
    valid = reason.isna()
    repeated = numbers[valid].drop(columns=ID_COLUMN).duplicated().reindex(raw.index, fill_value=False)
    reject(repeated, REJECT_DUPLICATE_RECORD)

    accepted = reason.isna()
    clean = numbers[accepted].astype({column: int for column in INTEGER_COLUMNS}).reset_index(drop=True)
    rejected = raw[~accepted].assign(reject_reason=reason[~accepted])
    return clean, rejected


# --- Transform --------------------------------------------------------------


def transform(clean: pd.DataFrame, measured_on: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Приводит чистые строки к таблицам patients и examinations (связь — по external_id)."""
    measured_at = datetime.combine(measured_on, datetime.min.time())
    patients = pd.DataFrame(
        {
            "external_id": clean[ID_COLUMN],
            "full_name": "Пациент №" + clean[ID_COLUMN].astype(str),
            # В датасете известен только возраст в днях на момент осмотра.
            "birth_date": [measured_on - timedelta(days=int(age)) for age in clean["age"]],
            "gender": clean["gender"].map(GENDER_LETTERS),
        }
    )
    examinations = pd.DataFrame(
        {
            "external_id": clean[ID_COLUMN],
            "measured_at": measured_at,
            **{column: clean[column] for column in ("height", "weight", "ap_hi", "ap_lo", "cholesterol", "gluc")},
            **{flag: clean[flag].astype(bool) for flag in ("smoke", "alco", "active")},
        }
    )
    return patients, examinations


# --- Load -------------------------------------------------------------------


def load(
    session: Session,
    clean: pd.DataFrame,
    measured_on: date,
    report: EtlReport,
    batch_size: int = DEFAULT_BATCH_SIZE,
    scorer: Callable[[pd.DataFrame], np.ndarray] | None = None,
    thresholds: tuple[float, float] = (0.4, 0.7),
) -> None:
    patients, examinations = transform(clean, measured_on)
    for start in range(0, len(clean), batch_size):
        batch = slice(start, start + batch_size)
        batch_patients = patients.iloc[batch]
        external_ids = batch_patients["external_id"].tolist()

        existing = set(session.scalars(select(Patient.external_id).where(Patient.external_id.in_(external_ids))))
        is_new = ~batch_patients["external_id"].isin(existing)
        report.skipped_existing += int((~is_new).sum())
        if not is_new.any():
            continue

        new_patients = batch_patients[is_new]
        session.execute(insert(Patient), _records(new_patients))
        ids = dict(
            session.execute(
                select(Patient.external_id, Patient.id).where(
                    Patient.external_id.in_(new_patients["external_id"].tolist())
                )
            ).all()
        )

        new_exams = examinations.iloc[batch][is_new.to_numpy()].copy()
        new_exams["patient_id"] = new_exams["external_id"].map(ids)
        if scorer is not None:
            probabilities = scorer(clean.iloc[batch][is_new.to_numpy()][FEATURE_COLUMNS])
            new_exams["risk_probability"] = probabilities
            new_exams["risk_level"] = [risk_service.classify(p, *thresholds) for p in probabilities]
            report.scored += len(new_exams)
        session.execute(insert(Examination), _records(new_exams.drop(columns="external_id")))
        session.commit()
        report.loaded += len(new_patients)
        logger.info("Загружено %d из %d", report.loaded, len(clean))


def _records(frame: pd.DataFrame) -> list[dict]:
    """Строки DataFrame как словари из обычных Python-типов (numpy-типы драйверы не принимают)."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


# --- Оркестрация и CLI ------------------------------------------------------


def run_import(
    session_factory: sessionmaker[Session],
    source: Path,
    *,
    measured_on: date = DEFAULT_MEASURED_ON,
    limit: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model_service: ModelService | None = None,
    settings: Settings | None = None,
    rejected_out: Path | None = None,
) -> EtlReport:
    started = time.perf_counter()
    report = EtlReport()
    settings = settings or Settings()

    raw = extract(source, limit)
    report.rows_read = len(raw)
    clean, rejected = validate_and_clean(raw)
    report.rejected = Counter(rejected["reject_reason"])
    for reason, count in sorted(report.rejected.items()):
        logger.warning("Отклонено %d строк: %s", count, reason)
    if rejected_out is not None and len(rejected):
        rejected.to_csv(rejected_out, index=False)
        logger.info("Отклонённые строки сохранены в %s", rejected_out)

    scorer = None
    if model_service is not None:
        scorer = lambda frame: risk_service.score(model_service, frame)  # noqa: E731

    with session_factory() as session:
        load(
            session,
            clean,
            measured_on,
            report,
            batch_size,
            scorer,
            (settings.risk_medium_threshold, settings.risk_high_threshold),
        )
    report.seconds = time.perf_counter() - started
    logger.info("ETL завершён: %s", report.summary())
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="CSV-файл (cardio_train.csv)")
    parser.add_argument("--limit", type=int, help="импортировать только первые N строк")
    parser.add_argument(
        "--measured-on",
        type=date.fromisoformat,
        default=DEFAULT_MEASURED_ON,
        help="дата осмотров в формате ГГГГ-ММ-ДД (по умолчанию 2020-01-01); от неё считается дата рождения",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--score", action="store_true", help="оценить риск загруженной ML-моделью (models/model.pkl)")
    parser.add_argument("--rejected-out", type=Path, help="куда сохранить отклонённые строки с причинами")
    parser.add_argument("--database-url", help="адрес БД; по умолчанию берётся из DATABASE_URL")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    args = parse_args(argv)
    settings = Settings()
    engine = create_db_engine(args.database_url or settings.database_url)

    model_service = None
    if args.score:
        model_service = ModelService(settings.model_path, settings.bundled_model_path)
        if not model_service.load_from_disk():
            logger.error(
                "Модель %s не найдена: обучите её (python -m ml.train) или уберите --score", settings.model_path
            )
            return 2
    try:
        report = run_import(
            create_session_factory(engine),
            args.source,
            measured_on=args.measured_on,
            limit=args.limit,
            batch_size=args.batch_size,
            model_service=model_service,
            settings=settings,
            rejected_out=args.rejected_out,
        )
    except EtlError as exc:
        logger.error("%s", exc)
        return 1
    finally:
        engine.dispose()
    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
