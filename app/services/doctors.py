"""Бизнес-логика врачей и справочника диагнозов."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Diagnosis, Doctor
from app.schemas.clinic import DiagnosisCreate, DoctorCreate, DoctorUpdate
from app.schemas.common import Page, Pagination
from app.services.common import commit_or_conflict, get_or_404, paginate


def create_doctor(db: Session, data: DoctorCreate) -> Doctor:
    doctor = Doctor(**data.model_dump())
    db.add(doctor)
    commit_or_conflict(db, "Врач с таким номером лицензии уже существует")
    return doctor


def get_doctor(db: Session, doctor_id: int) -> Doctor:
    return get_or_404(db, Doctor, doctor_id, "Врач")


def list_doctors(db: Session, page: Pagination, specialty: str | None = None, is_active: bool | None = None) -> Page:
    query = select(Doctor).order_by(Doctor.full_name, Doctor.id)
    if specialty:
        query = query.where(Doctor.specialty == specialty)
    if is_active is not None:
        query = query.where(Doctor.is_active == is_active)
    return paginate(db, query, page)


def update_doctor(db: Session, doctor_id: int, data: DoctorUpdate) -> Doctor:
    doctor = get_doctor(db, doctor_id)
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(doctor, field, value)
    db.commit()
    return doctor


def create_diagnosis(db: Session, data: DiagnosisCreate) -> Diagnosis:
    diagnosis = Diagnosis(**data.model_dump())
    db.add(diagnosis)
    commit_or_conflict(db, f"Диагноз с кодом {data.icd_code} уже есть в справочнике")
    return diagnosis


def list_diagnoses(db: Session, page: Pagination, search: str | None = None) -> Page:
    query = select(Diagnosis).order_by(Diagnosis.icd_code)
    if search:
        pattern = f"%{search}%"
        query = query.where(Diagnosis.name.ilike(pattern) | Diagnosis.icd_code.ilike(pattern))
    return paginate(db, query, page)
