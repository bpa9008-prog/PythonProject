"""Аналитические отчёты: агрегации, группировки, топ-N, динамика по периодам."""

from datetime import date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.orm import Session

from app.models import Appointment, Diagnosis, Doctor, Examination, Patient, appointment_diagnoses
from app.schemas.clinic import DoctorWorkload, FollowupPatient, RiskDynamicsPoint, TopDiagnosis
from app.schemas.common import Page, Pagination

Period = Literal["day", "month", "year"]

# Формат «усечения» даты до периода; PostgreSQL и SQLite называют функции по-разному.
PG_FORMATS = {"day": "YYYY-MM-DD", "month": "YYYY-MM", "year": "YYYY"}
SQLITE_FORMATS = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _period_bucket(db: Session, column, period: Period):
    if db.get_bind().dialect.name == "postgresql":
        return func.to_char(column, PG_FORMATS[period])
    return func.strftime(SQLITE_FORMATS[period], column)


def doctor_workload(db: Session, date_from: date | None = None, date_to: date | None = None) -> list[DoctorWorkload]:
    """Приёмы по врачам и статусам; врачи без приёмов тоже попадают в отчёт."""
    conditions = [Appointment.doctor_id == Doctor.id]
    if date_from:
        conditions.append(Appointment.scheduled_at >= _day_start(date_from))
    if date_to:
        conditions.append(Appointment.scheduled_at < _day_start(date_to + timedelta(days=1)))

    def count_status(status: str):
        return func.coalesce(func.sum(case((Appointment.status == status, 1), else_=0)), 0)

    rows = db.execute(
        select(
            Doctor.id,
            Doctor.full_name,
            Doctor.specialty,
            func.count(Appointment.id),
            count_status("scheduled"),
            count_status("completed"),
            count_status("cancelled"),
            count_status("no_show"),
        )
        .select_from(Doctor)
        .outerjoin(Appointment, and_(*conditions))
        .group_by(Doctor.id, Doctor.full_name, Doctor.specialty)
        .order_by(func.count(Appointment.id).desc(), Doctor.full_name)
    )
    result = []
    for doctor_id, name, specialty, total, scheduled, completed, cancelled, no_show in rows:
        attended = completed + no_show
        result.append(
            DoctorWorkload(
                doctor_id=doctor_id,
                full_name=name,
                specialty=specialty,
                total=total,
                scheduled=scheduled,
                completed=completed,
                cancelled=cancelled,
                no_show=no_show,
                completion_rate=round(completed / attended, 4) if attended else None,
            )
        )
    return result


def risk_dynamics(
    db: Session, period: Period = "month", date_from: date | None = None, date_to: date | None = None
) -> list[RiskDynamicsPoint]:
    """Число осмотров, средний риск и доля высокого риска по периодам."""
    bucket = _period_bucket(db, Examination.measured_at, period).label("period")
    high = func.sum(case((Examination.risk_level == "high", 1), else_=0))
    query = (
        select(bucket, func.count(Examination.id), func.avg(Examination.risk_probability), high)
        .where(Examination.risk_probability.is_not(None))
        .group_by(bucket)
        .order_by(bucket)
    )
    if date_from:
        query = query.where(Examination.measured_at >= _day_start(date_from))
    if date_to:
        query = query.where(Examination.measured_at < _day_start(date_to + timedelta(days=1)))
    return [
        RiskDynamicsPoint(
            period=label,
            examinations=count,
            avg_risk=round(float(avg), 4),
            high_risk=int(high_count),
            high_risk_share=round(int(high_count) / count, 4),
        )
        for label, count, avg, high_count in db.execute(query)
    ]


def top_diagnoses(db: Session, limit: int = 5) -> list[TopDiagnosis]:
    """Самые частые диагнозы по завершённым приёмам."""
    appointments = func.count(appointment_diagnoses.c.appointment_id)
    rows = db.execute(
        select(Diagnosis.icd_code, Diagnosis.name, appointments)
        .join(appointment_diagnoses, appointment_diagnoses.c.diagnosis_id == Diagnosis.id)
        .join(Appointment, Appointment.id == appointment_diagnoses.c.appointment_id)
        .where(Appointment.status == "completed")
        .group_by(Diagnosis.id, Diagnosis.icd_code, Diagnosis.name)
        .order_by(appointments.desc(), Diagnosis.icd_code)
        .limit(limit)
    )
    return [TopDiagnosis(icd_code=code, name=name, appointments=count) for code, name, count in rows]


def risk_followup(db: Session, page: Pagination) -> Page:
    """Пациенты, у которых последний осмотр показал высокий риск, а приёма после него нет."""
    # Последний осмотр пациента: по времени, а при равенстве — по id. Так на пациента ровно одна строка.
    ranked = select(
        Examination.id.label("id"),
        func.row_number()
        .over(
            partition_by=Examination.patient_id,
            order_by=(Examination.measured_at.desc(), Examination.id.desc()),
        )
        .label("rn"),
    ).subquery()
    followup_exists = exists().where(
        Appointment.patient_id == Patient.id,
        Appointment.status.in_(("scheduled", "completed")),
        Appointment.scheduled_at >= Examination.measured_at,
    )
    query = (
        select(Patient.id, Patient.full_name, Examination.measured_at, Examination.risk_probability)
        .join(Examination, Examination.patient_id == Patient.id)
        .join(ranked, ranked.c.id == Examination.id)
        .where(ranked.c.rn == 1, Examination.risk_level == "high", ~followup_exists)
        .order_by(Examination.risk_probability.desc(), Patient.id)
    )
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = db.execute(query.limit(page.limit).offset(page.offset))
    items = [
        FollowupPatient(patient_id=pid, full_name=name, measured_at=measured_at, risk_probability=prob)
        for pid, name, measured_at, prob in rows
    ]
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)
