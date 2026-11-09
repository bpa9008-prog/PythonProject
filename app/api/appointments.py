"""Эндпоинты приёмов: запись и смена статуса."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.api.deps import DbDep, NowDep, PageDep, SettingsDep
from app.schemas.clinic import AppointmentComplete, AppointmentCreate, AppointmentRead
from app.schemas.common import Page
from app.services import appointments

router = APIRouter(prefix="/appointments", tags=["appointments"])

NOT_FOUND = {404: {"description": "Приём не найден"}}
CONFLICT = {409: {"description": "Приём в неподходящем статусе или время занято"}}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Записать пациента на приём",
    responses={
        404: {"description": "Пациент или врач не найден"},
        409: {"description": "Врач или пациент заняты, либо врач не принимает"},
        422: {"description": "Время в прошлом или вне часов работы"},
    },
)
def book_appointment(data: AppointmentCreate, db: DbDep, now: NowDep, settings: SettingsDep) -> AppointmentRead:
    return appointments.book_appointment(db, data, now, settings)


@router.get("", summary="Список приёмов с фильтрами, сортировкой и пагинацией")
def list_appointments(
    db: DbDep,
    page: PageDep,
    patient_id: int | None = None,
    doctor_id: int | None = None,
    status: Annotated[Literal["scheduled", "completed", "cancelled", "no_show"] | None, Query()] = None,
    date_from: Annotated[date | None, Query(description="Начало периода, включительно")] = None,
    date_to: Annotated[date | None, Query(description="Конец периода, включительно")] = None,
    sort_by: Literal["id", "scheduled_at", "created_at"] = "scheduled_at",
    order: Literal["asc", "desc"] = "asc",
) -> Page[AppointmentRead]:
    return appointments.list_appointments(
        db, page, patient_id, doctor_id, status, date_from, date_to, sort_by, descending=order == "desc"
    )


@router.get("/{appointment_id}", summary="Получить приём", responses=NOT_FOUND)
def get_appointment(appointment_id: int, db: DbDep) -> AppointmentRead:
    return appointments.get_appointment(db, appointment_id)


@router.post(
    "/{appointment_id}/cancel",
    summary="Отменить приём (не позднее чем за MIN_CANCEL_HOURS до начала)",
    responses={**NOT_FOUND, **CONFLICT},
)
def cancel_appointment(appointment_id: int, db: DbDep, now: NowDep, settings: SettingsDep) -> AppointmentRead:
    return appointments.cancel_appointment(db, appointment_id, now, settings)


@router.post(
    "/{appointment_id}/complete",
    summary="Завершить приём и поставить диагнозы",
    responses={**NOT_FOUND, **CONFLICT, 422: {"description": "Приём ещё не начался или нужен диагноз"}},
)
def complete_appointment(
    appointment_id: int, db: DbDep, now: NowDep, data: AppointmentComplete | None = None
) -> AppointmentRead:
    return appointments.complete_appointment(db, appointment_id, data or AppointmentComplete(), now)


@router.post(
    "/{appointment_id}/no-show",
    summary="Отметить неявку пациента",
    responses={**NOT_FOUND, **CONFLICT, 422: {"description": "Время приёма ещё не вышло"}},
)
def mark_no_show(appointment_id: int, db: DbDep, now: NowDep) -> AppointmentRead:
    return appointments.mark_no_show(db, appointment_id, now)
