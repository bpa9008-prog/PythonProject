from datetime import datetime

from sqlalchemy import func, select

from app.models import Appointment, Diagnosis, Doctor, Examination, Patient
from app.seed import seed
from app.services.model_service import ModelService

NOW = datetime(2026, 11, 9, 9, 0)


def counts(db) -> dict[str, int]:
    return {
        model.__name__: db.scalar(select(func.count()).select_from(model))
        for model in (Doctor, Diagnosis, Patient, Examination, Appointment)
    }


def test_seed_fills_database_with_scored_examinations(db, settings, model_bytes):
    settings.model_path.write_bytes(model_bytes)
    model_service = ModelService(settings.model_path)
    model_service.load_from_disk()

    created = seed(db, settings, model_service, NOW)

    assert created == {"doctors": 5, "diagnoses": 10, "patients": 6, "examinations": 6, "appointments": 4}
    assert counts(db) == {"Doctor": 5, "Diagnosis": 10, "Patient": 6, "Examination": 6, "Appointment": 4}
    assert db.scalar(select(func.count()).where(Examination.risk_level.is_(None))) == 0


def test_seed_is_idempotent(db, settings, model_bytes):
    settings.model_path.write_bytes(model_bytes)
    model_service = ModelService(settings.model_path)
    model_service.load_from_disk()
    seed(db, settings, model_service, NOW)
    before = counts(db)

    second = seed(db, settings, model_service, NOW)

    assert set(second.values()) == {0}
    assert counts(db) == before


def test_seed_without_model_skips_examinations(db, settings):
    created = seed(db, settings, None, NOW)

    assert created["examinations"] == 0
    assert created["patients"] == 6
