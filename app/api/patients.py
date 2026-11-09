"""Эндпоинты пациентов и их медосмотров."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DbDep, ModelServiceDep, NowDep, PageDep, SettingsDep
from app.schemas.clinic import ExaminationCreate, ExaminationRead, PatientCreate, PatientRead, PatientUpdate
from app.schemas.common import Page
from app.services import examinations, patients

router = APIRouter(tags=["patients"])

NOT_FOUND = {404: {"description": "Пациент не найден"}}


@router.post(
    "/patients",
    status_code=status.HTTP_201_CREATED,
    summary="Создать пациента",
    responses={409: {"description": "Телефон уже занят"}},
)
def create_patient(data: PatientCreate, db: DbDep) -> PatientRead:
    return patients.create_patient(db, data)


@router.get("/patients", summary="Список пациентов с поиском, фильтром, сортировкой и пагинацией")
def list_patients(
    db: DbDep,
    page: PageDep,
    search: Annotated[str | None, Query(description="Подстрока в ФИО, без учёта регистра")] = None,
    gender: Annotated[Literal["F", "M"] | None, Query(description="Фильтр по полу")] = None,
    sort_by: Literal["id", "full_name", "birth_date", "created_at"] = "full_name",
    order: Literal["asc", "desc"] = "asc",
) -> Page[PatientRead]:
    return patients.list_patients(db, page, search, gender, sort_by, descending=order == "desc")


@router.get("/patients/{patient_id}", summary="Получить пациента", responses=NOT_FOUND)
def get_patient(patient_id: int, db: DbDep) -> PatientRead:
    return patients.get_patient(db, patient_id)


@router.patch(
    "/patients/{patient_id}",
    summary="Частично обновить пациента",
    responses={**NOT_FOUND, 409: {"description": "Телефон уже занят"}},
)
def update_patient(patient_id: int, data: PatientUpdate, db: DbDep) -> PatientRead:
    return patients.update_patient(db, patient_id, data)


@router.delete(
    "/patients/{patient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить пациента без приёмов",
    responses={**NOT_FOUND, 409: {"description": "У пациента есть приёмы"}},
)
def delete_patient(patient_id: int, db: DbDep) -> Response:
    patients.delete_patient(db, patient_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/patients/{patient_id}/examinations",
    status_code=status.HTTP_201_CREATED,
    summary="Добавить медосмотр и получить оценку риска от ML-модели",
    responses={**NOT_FOUND, 422: {"description": "Невалидные данные"}, 503: {"description": "Модель не загружена"}},
)
def create_examination(
    patient_id: int,
    data: ExaminationCreate,
    db: DbDep,
    model_service: ModelServiceDep,
    settings: SettingsDep,
    now: NowDep,
) -> ExaminationRead:
    return examinations.create_examination(db, model_service, patient_id, data, now, settings)


@router.get("/patients/{patient_id}/examinations", summary="История осмотров пациента", responses=NOT_FOUND)
def list_examinations(patient_id: int, db: DbDep, page: PageDep) -> Page[ExaminationRead]:
    return examinations.list_examinations(db, patient_id, page)
