"""Бизнес-логика пациентов."""

from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import Appointment, Patient
from app.schemas.clinic import PatientCreate, PatientUpdate
from app.schemas.common import Page, Pagination
from app.services.common import commit_or_conflict, get_or_404, paginate

SORT_COLUMNS = {
    "id": Patient.id,
    "full_name": Patient.full_name,
    "birth_date": Patient.birth_date,
    "created_at": Patient.created_at,
}
PHONE_TAKEN = "Пациент с таким телефоном уже существует"


def create_patient(db: Session, data: PatientCreate) -> Patient:
    patient = Patient(**data.model_dump())
    db.add(patient)
    commit_or_conflict(db, PHONE_TAKEN)
    return patient


def get_patient(db: Session, patient_id: int) -> Patient:
    return get_or_404(db, Patient, patient_id, "Пациент")


def list_patients(
    db: Session,
    page: Pagination,
    search: str | None = None,
    gender: Literal["F", "M"] | None = None,
    sort_by: str = "full_name",
    descending: bool = False,
) -> Page:
    query = select(Patient)
    if search:
        query = query.where(Patient.full_name.ilike(f"%{search}%"))
    if gender:
        query = query.where(Patient.gender == gender)
    column = SORT_COLUMNS[sort_by]
    # id во вторичной сортировке делает порядок стабильным для пагинации.
    query = query.order_by(column.desc() if descending else column.asc(), Patient.id)
    return paginate(db, query, page)


def update_patient(db: Session, patient_id: int, data: PatientUpdate) -> Patient:
    patient = get_patient(db, patient_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is None and field != "phone":
            continue  # обязательные поля нельзя обнулить
        setattr(patient, field, value)
    commit_or_conflict(db, PHONE_TAKEN)
    return patient


def delete_patient(db: Session, patient_id: int) -> None:
    patient = get_patient(db, patient_id)
    # История приёмов — медицинский документ, её нельзя потерять вместе с пациентом.
    if db.scalar(select(exists().where(Appointment.patient_id == patient_id))):
        raise ConflictError("Нельзя удалить пациента, у которого есть приёмы")
    db.delete(patient)
    db.commit()
