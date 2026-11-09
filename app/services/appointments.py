"""Запись на приём и жизненный цикл приёма.

Бизнес-правила:
1. Запись возможна только на будущее время, в часы работы клиники и к действующему врачу.
2. Врач и пациент не могут иметь два пересекающихся приёма.
3. Статус меняется только из «scheduled»: в completed, cancelled или no_show.
   Отменить можно не позднее чем за MIN_CANCEL_HOURS часов до начала.
4. Приём нельзя завершить до его начала, а если последний осмотр пациента показал высокий риск —
   без диагноза.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import Appointment, Diagnosis, Doctor, Examination, Patient
from app.schemas.clinic import AppointmentComplete, AppointmentCreate
from app.schemas.common import Page, Pagination
from app.services.common import commit_or_conflict, get_or_404, paginate

# Статусы, при которых время врача занято.
BUSY_STATUSES = ("scheduled", "completed")
SORT_COLUMNS = {
    "id": Appointment.id,
    "scheduled_at": Appointment.scheduled_at,
    "created_at": Appointment.created_at,
}


def _to_clinic_time(moment: datetime, settings: Settings) -> datetime:
    return moment.replace(tzinfo=UTC).astimezone(ZoneInfo(settings.clinic_timezone)).replace(tzinfo=None)


def _validate_working_hours(start: datetime, end: datetime, settings: Settings) -> None:
    """Приём целиком должен лежать в рабочем дне клиники (в её часовом поясе)."""
    local_start, local_end = _to_clinic_time(start, settings), _to_clinic_time(end, settings)
    opens = datetime.combine(local_start.date(), time(settings.clinic_open_hour))
    closes = datetime.combine(local_start.date(), time(settings.clinic_close_hour))
    if local_start < opens or local_end > closes:
        raise BusinessRuleError(
            f"Клиника принимает с {settings.clinic_open_hour}:00 до {settings.clinic_close_hour}:00 "
            f"({settings.clinic_timezone}); приём должен целиком попадать в этот интервал"
        )


def _overlaps(column_owner, owner_id: int, start: datetime, end: datetime):
    """Условие «у владельца есть пересекающийся приём»; column_owner — Appointment.doctor_id/patient_id."""
    return exists().where(
        column_owner == owner_id,
        Appointment.status.in_(BUSY_STATUSES),
        Appointment.scheduled_at < end,
        Appointment.ends_at > start,
    )


def book_appointment(db: Session, data: AppointmentCreate, now: datetime, settings: Settings) -> Appointment:
    if data.scheduled_at <= now:
        raise BusinessRuleError("Нельзя записаться на прошедшее время")
    ends_at = data.scheduled_at + timedelta(minutes=data.duration_minutes)
    _validate_working_hours(data.scheduled_at, ends_at, settings)

    # Блокировка строки врача сериализует параллельные записи к нему (в PostgreSQL; в SQLite игнорируется).
    doctor = db.scalar(select(Doctor).where(Doctor.id == data.doctor_id).with_for_update())
    if doctor is None:
        raise NotFoundError("Врач", data.doctor_id)
    get_or_404(db, Patient, data.patient_id, "Пациент")
    if not doctor.is_active:
        raise ConflictError("Врач сейчас не принимает пациентов")

    if db.scalar(select(_overlaps(Appointment.doctor_id, data.doctor_id, data.scheduled_at, ends_at))):
        raise ConflictError("Врач занят в это время")
    if db.scalar(select(_overlaps(Appointment.patient_id, data.patient_id, data.scheduled_at, ends_at))):
        raise ConflictError("У пациента уже есть приём в это время")

    appointment = Appointment(
        patient_id=data.patient_id,
        doctor_id=data.doctor_id,
        scheduled_at=data.scheduled_at,
        ends_at=ends_at,
        reason=data.reason,
    )
    db.add(appointment)
    # Подстраховка от гонки: частичный уникальный индекс не даст занять один слот дважды.
    commit_or_conflict(db, "Это время уже занято")
    return get_appointment(db, appointment.id)


def get_appointment(db: Session, appointment_id: int) -> Appointment:
    appointment = db.scalar(
        select(Appointment).where(Appointment.id == appointment_id).options(selectinload(Appointment.diagnoses))
    )
    if appointment is None:
        raise NotFoundError("Приём", appointment_id)
    return appointment


def list_appointments(
    db: Session,
    page: Pagination,
    patient_id: int | None = None,
    doctor_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort_by: Literal["id", "scheduled_at", "created_at"] = "scheduled_at",
    descending: bool = False,
) -> Page:
    query = select(Appointment).options(selectinload(Appointment.diagnoses))
    if patient_id is not None:
        query = query.where(Appointment.patient_id == patient_id)
    if doctor_id is not None:
        query = query.where(Appointment.doctor_id == doctor_id)
    if status:
        query = query.where(Appointment.status == status)
    if date_from:
        query = query.where(Appointment.scheduled_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.where(Appointment.scheduled_at < datetime.combine(date_to + timedelta(days=1), time.min))
    column = SORT_COLUMNS[sort_by]
    query = query.order_by(column.desc() if descending else column.asc(), Appointment.id)
    return paginate(db, query, page)


def _require_scheduled(appointment: Appointment, action: str) -> None:
    if appointment.status != "scheduled":
        raise ConflictError(f"Нельзя {action}: приём уже в статусе «{appointment.status}»")


def cancel_appointment(db: Session, appointment_id: int, now: datetime, settings: Settings) -> Appointment:
    appointment = get_appointment(db, appointment_id)
    _require_scheduled(appointment, "отменить")
    if appointment.scheduled_at - now < timedelta(hours=settings.min_cancel_hours):
        raise ConflictError(f"Отменить приём можно не позднее чем за {settings.min_cancel_hours} ч до начала")
    appointment.status = "cancelled"
    db.commit()
    return appointment


def mark_no_show(db: Session, appointment_id: int, now: datetime) -> Appointment:
    appointment = get_appointment(db, appointment_id)
    _require_scheduled(appointment, "отметить неявку")
    if now < appointment.ends_at:
        raise BusinessRuleError("Неявку можно отметить только после окончания времени приёма")
    appointment.status = "no_show"
    db.commit()
    return appointment


def complete_appointment(db: Session, appointment_id: int, data: AppointmentComplete, now: datetime) -> Appointment:
    appointment = get_appointment(db, appointment_id)
    _require_scheduled(appointment, "завершить")
    if appointment.scheduled_at > now:
        raise BusinessRuleError("Нельзя завершить приём до его начала")

    diagnoses: list[Diagnosis] = []
    if data.diagnosis_ids:
        unique_ids = set(data.diagnosis_ids)
        diagnoses = list(db.scalars(select(Diagnosis).where(Diagnosis.id.in_(unique_ids))))
        missing = unique_ids - {d.id for d in diagnoses}
        if missing:
            raise NotFoundError("Диагноз", ", ".join(map(str, sorted(missing))))

    if not diagnoses and _latest_risk_level(db, appointment.patient_id) == "high":
        raise BusinessRuleError("У пациента высокий риск по последнему осмотру: укажите хотя бы один диагноз")

    # Порядок как у relationship (по коду МКБ): коллекция после commit не перечитывается из БД.
    appointment.diagnoses = sorted(diagnoses, key=lambda diagnosis: diagnosis.icd_code)
    appointment.notes = data.notes
    appointment.status = "completed"
    db.commit()
    return appointment


def _latest_risk_level(db: Session, patient_id: int) -> str | None:
    return db.scalar(
        select(Examination.risk_level)
        .where(Examination.patient_id == patient_id, Examination.risk_level.is_not(None))
        .order_by(Examination.measured_at.desc(), Examination.id.desc())
        .limit(1)
    )
