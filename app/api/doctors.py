"""Эндпоинты врачей и справочника диагнозов."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbDep, PageDep
from app.schemas.clinic import DiagnosisCreate, DiagnosisRead, DoctorCreate, DoctorRead, DoctorUpdate
from app.schemas.common import Page
from app.services import doctors

router = APIRouter(tags=["doctors"])


@router.post(
    "/doctors",
    status_code=status.HTTP_201_CREATED,
    summary="Добавить врача",
    responses={409: {"description": "Номер лицензии уже занят"}},
)
def create_doctor(data: DoctorCreate, db: DbDep) -> DoctorRead:
    return doctors.create_doctor(db, data)


@router.get("/doctors", summary="Список врачей с фильтрами по специальности и активности")
def list_doctors(
    db: DbDep,
    page: PageDep,
    specialty: Annotated[str | None, Query(description="Точное название специальности")] = None,
    is_active: bool | None = None,
) -> Page[DoctorRead]:
    return doctors.list_doctors(db, page, specialty, is_active)


@router.get("/doctors/{doctor_id}", summary="Получить врача", responses={404: {"description": "Врач не найден"}})
def get_doctor(doctor_id: int, db: DbDep) -> DoctorRead:
    return doctors.get_doctor(db, doctor_id)


@router.patch(
    "/doctors/{doctor_id}",
    summary="Обновить врача (в том числе отключить приём)",
    responses={404: {"description": "Врач не найден"}},
)
def update_doctor(doctor_id: int, data: DoctorUpdate, db: DbDep) -> DoctorRead:
    return doctors.update_doctor(db, doctor_id, data)


@router.post(
    "/diagnoses",
    status_code=status.HTTP_201_CREATED,
    tags=["diagnoses"],
    summary="Добавить диагноз в справочник",
    responses={409: {"description": "Код уже есть в справочнике"}},
)
def create_diagnosis(data: DiagnosisCreate, db: DbDep) -> DiagnosisRead:
    return doctors.create_diagnosis(db, data)


@router.get("/diagnoses", tags=["diagnoses"], summary="Справочник диагнозов")
def list_diagnoses(
    db: DbDep,
    page: PageDep,
    search: Annotated[str | None, Query(description="Подстрока в коде или названии")] = None,
) -> Page[DiagnosisRead]:
    return doctors.list_diagnoses(db, page, search)
