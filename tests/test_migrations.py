"""Миграции Alembic: применяются, обратимы и соответствуют моделям."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.core.database import Base

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TABLES = {"patients", "doctors", "diagnoses", "appointments", "appointment_diagnoses", "examinations"}


@pytest.fixture
def db_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'migrations.db'}"


@pytest.fixture
def alembic_config(db_url) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_creates_all_tables(alembic_config, db_url):
    command.upgrade(alembic_config, "head")

    assert table_names(db_url) == EXPECTED_TABLES


def test_downgrade_removes_everything_and_can_be_reapplied(alembic_config, db_url):
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    assert table_names(db_url) == set()

    command.upgrade(alembic_config, "head")
    assert table_names(db_url) == EXPECTED_TABLES


def test_models_match_migrations(alembic_config, db_url):
    """Если модель изменили, а миграцию не добавили, этот тест покажет расхождение."""
    command.upgrade(alembic_config, "head")
    engine = create_engine(db_url)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    engine.dispose()

    assert differences == []


def test_schema_has_required_indexes_and_constraints(alembic_config, db_url):
    command.upgrade(alembic_config, "head")
    engine = create_engine(db_url)
    inspector = inspect(engine)

    indexes = {t: {tuple(i["column_names"]) for i in inspector.get_indexes(t)} for t in EXPECTED_TABLES}
    appointment_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("appointments")}
    patient_checks = {c["name"] for c in inspector.get_check_constraints("patients")}
    engine.dispose()

    assert ("full_name",) in indexes["patients"]
    assert ("doctor_id", "scheduled_at") in indexes["appointments"]
    assert ("status",) in indexes["appointments"]
    assert ("patient_id", "measured_at") in indexes["examinations"]
    assert appointment_fks == {"patients", "doctors"}
    assert patient_checks == {"ck_patients_gender_valid"}
