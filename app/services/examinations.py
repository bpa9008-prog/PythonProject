"""Медосмотры: сохранение результатов и оценка риска ML-моделью.

Бизнес-правило: осмотр сохраняется только вместе с оценкой риска. Если модель не загружена,
операция отклоняется (503), чтобы в истории не появлялись осмотры без вывода о риске.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import BusinessRuleError
from app.models import Examination
from app.schemas.clinic import ExaminationCreate
from app.schemas.common import Page, Pagination
from app.services import risk_service
from app.services.common import paginate
from app.services.model_service import ModelService
from app.services.patients import get_patient

MIN_AGE_YEARS = 18


def create_examination(
    db: Session,
    model_service: ModelService,
    patient_id: int,
    data: ExaminationCreate,
    now: datetime,
    settings: Settings,
) -> Examination:
    patient = get_patient(db, patient_id)
    measured_at = data.measured_at or now
    if measured_at > now:
        raise BusinessRuleError("Дата осмотра не может быть в будущем")
    age_days = risk_service.age_in_days(patient.birth_date, measured_at.date())
    if age_days < MIN_AGE_YEARS * risk_service.DAYS_IN_YEAR:
        raise BusinessRuleError("Модель оценивает риск только для пациентов старше 18 лет")

    row = {
        "age": age_days,
        "gender": patient.gender,
        **data.model_dump(exclude={"measured_at"}),
    }
    probability = float(risk_service.score(model_service, risk_service.build_feature_frame([row]))[0])

    examination = Examination(
        patient_id=patient_id,
        measured_at=measured_at,
        **data.model_dump(exclude={"measured_at"}),
        risk_probability=probability,
        risk_level=risk_service.classify(probability, settings.risk_medium_threshold, settings.risk_high_threshold),
    )
    db.add(examination)
    db.commit()
    return examination


def list_examinations(db: Session, patient_id: int, page: Pagination) -> Page:
    get_patient(db, patient_id)
    query = (
        select(Examination)
        .where(Examination.patient_id == patient_id)
        .order_by(Examination.measured_at.desc(), Examination.id.desc())
    )
    return paginate(db, query, page)
