"""Аналитические эндпоинты."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbDep, PageDep
from app.schemas.clinic import DoctorWorkload, FollowupPatient, RiskDynamicsPoint, TopDiagnosis
from app.schemas.common import Page
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])

DateFrom = Annotated[date | None, Query(description="Начало периода, включительно")]
DateTo = Annotated[date | None, Query(description="Конец периода, включительно")]


@router.get("/doctor-workload", summary="Загрузка врачей: приёмы по статусам и доля состоявшихся")
def doctor_workload(db: DbDep, date_from: DateFrom = None, date_to: DateTo = None) -> list[DoctorWorkload]:
    return analytics.doctor_workload(db, date_from, date_to)


@router.get("/risk-dynamics", summary="Динамика риска: число осмотров, средний риск и доля высокого по периодам")
def risk_dynamics(
    db: DbDep,
    period: analytics.Period = "month",
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> list[RiskDynamicsPoint]:
    return analytics.risk_dynamics(db, period, date_from, date_to)


@router.get("/top-diagnoses", summary="Топ-N самых частых диагнозов по завершённым приёмам")
def top_diagnoses(db: DbDep, limit: Annotated[int, Query(ge=1, le=50)] = 5) -> list[TopDiagnosis]:
    return analytics.top_diagnoses(db, limit)


@router.get("/risk-followup", summary="Пациенты с высоким риском, которых не записали на приём после осмотра")
def risk_followup(db: DbDep, page: PageDep) -> Page[FollowupPatient]:
    return analytics.risk_followup(db, page)
