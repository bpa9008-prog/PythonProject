"""Наполнение БД демонстрационными данными: врачи, справочник диагнозов, пациенты, приёмы, осмотры.

Запуск: python -m app.seed
Скрипт идемпотентен: существующие записи (по лицензии, коду МКБ, телефону) пропускаются.
"""

import logging
import sys
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.database import create_db_engine, create_session_factory
from app.core.errors import ServiceError
from app.models import Diagnosis, Doctor, Patient
from app.schemas.clinic import AppointmentCreate, ExaminationCreate
from app.services import appointments, examinations
from app.services.model_service import ModelService

logger = logging.getLogger("app.seed")

DOCTORS = [
    ("Смирнова Елена Викторовна", "Кардиолог", "MD-0001"),
    ("Кузнецов Андрей Павлович", "Кардиолог", "MD-0002"),
    ("Орлова Мария Сергеевна", "Терапевт", "MD-0003"),
    ("Волков Дмитрий Игоревич", "Эндокринолог", "MD-0004"),
    ("Новикова Ирина Олеговна", "Кардиолог", "MD-0005"),
]
DIAGNOSES = [
    ("I10", "Эссенциальная (первичная) гипертензия"),
    ("I20", "Стенокардия"),
    ("I21", "Острый инфаркт миокарда"),
    ("I25", "Хроническая ишемическая болезнь сердца"),
    ("I48", "Фибрилляция и трепетание предсердий"),
    ("I50", "Сердечная недостаточность"),
    ("E78", "Нарушения обмена липопротеидов (дислипидемия)"),
    ("E66", "Ожирение"),
    ("E11", "Сахарный диабет 2 типа"),
    ("R03", "Повышенное артериальное давление без диагноза гипертензии"),
]
# ФИО, дата рождения, пол, телефон, осмотр (рост, вес, АД верх/низ, холестерин, глюкоза, курение, алкоголь, активность)
PATIENTS = [
    ("Иванов Иван Иванович", date(1965, 3, 14), "M", "+79990000001", (176, 98, 165, 100, 3, 2, True, False, False)),
    ("Петрова Анна Сергеевна", date(1988, 7, 2), "F", "+79990000002", (165, 58, 112, 72, 1, 1, False, False, True)),
    ("Сидоров Олег Николаевич", date(1972, 11, 23), "M", "+79990000003", (181, 92, 148, 94, 2, 1, True, True, True)),
    ("Кравцова Ольга Андреевна", date(1958, 1, 30), "F", "+79990000004", (160, 81, 158, 96, 3, 3, False, False, False)),
    ("Белов Артём Викторович", date(1995, 5, 9), "M", "+79990000005", (183, 79, 118, 76, 1, 1, False, False, True)),
    ("Захарова Нина Павловна", date(1950, 9, 17), "F", "+79990000006", (158, 74, 170, 104, 2, 2, False, False, False)),
]


def next_weekday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def seed(session: Session, settings: Settings, model_service: ModelService | None = None, now: datetime | None = None):
    now = now or utcnow()
    created = {"doctors": 0, "diagnoses": 0, "patients": 0, "examinations": 0, "appointments": 0}

    for full_name, specialty, license_number in DOCTORS:
        if session.scalar(select(Doctor).where(Doctor.license_number == license_number)) is None:
            session.add(Doctor(full_name=full_name, specialty=specialty, license_number=license_number))
            created["doctors"] += 1
    for code, name in DIAGNOSES:
        if session.scalar(select(Diagnosis).where(Diagnosis.icd_code == code)) is None:
            session.add(Diagnosis(icd_code=code, name=name))
            created["diagnoses"] += 1
    session.commit()

    patients = []
    for full_name, birth_date, gender, phone, _ in PATIENTS:
        patient = session.scalar(select(Patient).where(Patient.phone == phone))
        if patient is None:
            patient = Patient(full_name=full_name, birth_date=birth_date, gender=gender, phone=phone)
            session.add(patient)
            session.commit()
            created["patients"] += 1
            patients.append((patient, True))
        else:
            patients.append((patient, False))

    if model_service is not None and model_service.is_loaded:
        for (patient, is_new), (*_, exam) in zip(patients, PATIENTS, strict=True):
            if not is_new:
                continue
            height, weight, ap_hi, ap_lo, cholesterol, gluc, smoke, alco, active = exam
            data = ExaminationCreate(
                height=height, weight=weight, ap_hi=ap_hi, ap_lo=ap_lo, cholesterol=cholesterol, gluc=gluc,
                smoke=smoke, alco=alco, active=active,
            )  # fmt: skip
            examinations.create_examination(session, model_service, patient.id, data, now, settings)
            created["examinations"] += 1
    else:
        logger.warning("Модель не загружена: осмотры пропущены (обучите её: python -m ml.train)")

    # Приёмы создаются теми же бизнес-правилами, что и через API; занятые слоты пропускаем.
    cardiologist = session.scalar(select(Doctor).where(Doctor.license_number == "MD-0001"))
    visit_day = next_weekday(now.date())
    for index, (patient, _) in enumerate(patients[:4]):
        # Часы работы заданы в часовом поясе клиники, а в БД время хранится в UTC.
        local_start = datetime.combine(
            visit_day, time(settings.clinic_open_hour + 1 + index), tzinfo=ZoneInfo(settings.clinic_timezone)
        )
        start = local_start.astimezone(UTC).replace(tzinfo=None)
        try:
            appointments.book_appointment(
                session,
                AppointmentCreate(
                    patient_id=patient.id,
                    doctor_id=cardiologist.id,
                    scheduled_at=start,
                    duration_minutes=30,
                    reason="Плановый осмотр",
                ),
                now,
                settings,
            )
            created["appointments"] += 1
        except ServiceError as exc:
            logger.info("Приём пропущен: %s", exc.detail)
    return created


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    settings = Settings()
    engine = create_db_engine(settings.database_url)
    model_service = ModelService(settings.model_path, settings.bundled_model_path)
    model_service.load_from_disk()
    with create_session_factory(engine)() as session:
        created = seed(session, settings, model_service)
    engine.dispose()
    print("Создано:", ", ".join(f"{name}={count}" for name, count in created.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
