"""Unit-тесты сервисного слоя и ограничений целостности БД (без HTTP)."""

from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import Appointment, Doctor, Examination, Patient
from app.schemas.clinic import AppointmentComplete, AppointmentCreate, PatientCreate, PatientUpdate
from app.schemas.common import Pagination
from app.services import appointments, patients, risk_service

NOW = datetime(2026, 11, 9, 9, 0)
SETTINGS = Settings(clinic_open_hour=8, clinic_close_hour=20, min_cancel_hours=2)


@pytest.fixture
def people(db):
    patient = Patient(full_name="Иванов Иван", birth_date=date(1970, 1, 1), gender="M")
    doctor = Doctor(full_name="Петров Пётр", specialty="Кардиолог", license_number="MD-0001")
    db.add_all([patient, doctor])
    db.commit()
    return patient, doctor


def booking(patient, doctor, start: datetime, minutes: int = 30) -> AppointmentCreate:
    return AppointmentCreate(patient_id=patient.id, doctor_id=doctor.id, scheduled_at=start, duration_minutes=minutes)


# --- Запись: границы рабочего дня ------------------------------------------


@pytest.mark.parametrize(
    ("start", "minutes", "allowed"),
    [
        (datetime(2026, 11, 10, 8, 0), 30, True),  # ровно к открытию
        (datetime(2026, 11, 10, 19, 30), 30, True),  # заканчивается ровно в закрытие
        (datetime(2026, 11, 10, 19, 45), 30, False),  # выходит за закрытие
        (datetime(2026, 11, 10, 7, 45), 30, False),  # начинается до открытия
    ],
)
def test_working_hours_boundaries(db, people, start, minutes, allowed):
    patient, doctor = people

    if allowed:
        assert appointments.book_appointment(db, booking(patient, doctor, start, minutes), NOW, SETTINGS).id
    else:
        with pytest.raises(BusinessRuleError):
            appointments.book_appointment(db, booking(patient, doctor, start, minutes), NOW, SETTINGS)


def test_booking_exactly_now_is_rejected(db, people):
    patient, doctor = people

    with pytest.raises(BusinessRuleError, match="прошедшее"):
        appointments.book_appointment(db, booking(patient, doctor, NOW), NOW, SETTINGS)


def test_cancelled_appointment_does_not_block_the_slot(db, people):
    patient, doctor = people
    start = datetime(2026, 11, 10, 10, 0)
    first = appointments.book_appointment(db, booking(patient, doctor, start), NOW, SETTINGS)
    appointments.cancel_appointment(db, first.id, NOW, SETTINGS)

    second = appointments.book_appointment(db, booking(patient, doctor, start), NOW, SETTINGS)

    assert second.id != first.id


def test_cancel_boundary_is_exactly_min_hours(db, people):
    patient, doctor = people
    appointment = appointments.book_appointment(
        db, booking(patient, doctor, datetime(2026, 11, 10, 10, 0)), NOW, SETTINGS
    )

    with pytest.raises(ConflictError):
        appointments.cancel_appointment(db, appointment.id, datetime(2026, 11, 10, 8, 1), SETTINGS)
    assert appointments.cancel_appointment(db, appointment.id, datetime(2026, 11, 10, 8, 0), SETTINGS).status == (
        "cancelled"
    )


def test_complete_uses_latest_examination_for_high_risk_rule(db, people):
    patient, doctor = people
    appointment = appointments.book_appointment(
        db, booking(patient, doctor, datetime(2026, 11, 10, 10, 0)), NOW, SETTINGS
    )
    base = {"height": 170, "weight": 80, "ap_hi": 130, "ap_lo": 85, "cholesterol": 1, "gluc": 1}
    db.add_all(
        [
            Examination(patient_id=patient.id, measured_at=datetime(2026, 1, 1), risk_level="high", **base),
            # Более свежий осмотр без высокого риска отменяет требование.
            Examination(patient_id=patient.id, measured_at=datetime(2026, 6, 1), risk_level="low", **base),
        ]
    )
    db.commit()

    done = appointments.complete_appointment(db, appointment.id, AppointmentComplete(), datetime(2026, 11, 10, 10, 1))

    assert done.status == "completed"


def test_unknown_ids_raise_not_found(db, people):
    patient, doctor = people

    with pytest.raises(NotFoundError):
        appointments.book_appointment(
            db, booking(Patient(id=999), doctor, datetime(2026, 11, 10, 10, 0)), NOW, SETTINGS
        )
    with pytest.raises(NotFoundError):
        appointments.cancel_appointment(db, 999, NOW, SETTINGS)
    with pytest.raises(NotFoundError):
        patients.get_patient(db, patient.id + 100)


# --- Пациенты ---------------------------------------------------------------


def test_update_patient_ignores_null_for_required_fields_but_clears_phone(db):
    patient = patients.create_patient(
        db, PatientCreate(full_name="Иванов Иван", birth_date=date(1970, 1, 1), gender="M", phone="+79990000001")
    )

    patients.update_patient(db, patient.id, PatientUpdate(full_name=None, phone=None))

    assert patient.full_name == "Иванов Иван"
    assert patient.phone is None


def test_list_patients_sort_is_stable_for_equal_keys(db):
    for _ in range(5):
        db.add(Patient(full_name="Однофамилец", birth_date=date(1980, 1, 1), gender="F"))
    db.commit()

    ids = [p.id for page in range(5) for p in patients.list_patients(db, Pagination(1, page)).items]

    assert ids == sorted(ids)


# --- Риск -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("probability", "level"),
    [(0.0, "low"), (0.399, "low"), (0.4, "medium"), (0.699, "medium"), (0.7, "high"), (1.0, "high")],
)
def test_classify_risk_levels(probability, level):
    assert risk_service.classify(probability, 0.4, 0.7) == level


def test_build_feature_frame_encodes_gender_and_flags():
    frame = risk_service.build_feature_frame(
        [{"age": 18000, "gender": "F", "smoke": True, "alco": False, "active": True, "ap_hi": 120}]
    )

    assert frame.loc[0, "gender"] == 1
    assert frame.loc[0, ["smoke", "alco", "active"]].tolist() == [1, 0, 1]


# --- Ограничения целостности БД --------------------------------------------


def _appointment(patient, doctor, start, end, status="scheduled"):
    return Appointment(patient_id=patient.id, doctor_id=doctor.id, scheduled_at=start, ends_at=end, status=status)


def test_db_rejects_invalid_status_and_inverted_interval(db, people):
    patient, doctor = people
    start = datetime(2026, 11, 10, 10, 0)

    for bad in (
        _appointment(patient, doctor, start, datetime(2026, 11, 10, 10, 30), status="unknown"),
        _appointment(patient, doctor, start, start),
    ):
        db.add(bad)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_db_forbids_two_active_appointments_in_the_same_slot(db, people):
    patient, doctor = people
    start, end = datetime(2026, 11, 10, 10, 0), datetime(2026, 11, 10, 10, 30)
    db.add(_appointment(patient, doctor, start, end))
    db.commit()

    db.add(_appointment(patient, doctor, start, end))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(_appointment(patient, doctor, start, end, status="cancelled"))
    db.commit()  # отменённый приём слот не занимает


def test_db_checks_on_examinations_and_patients(db, people):
    patient, _ = people
    valid = {"height": 170, "weight": 80, "ap_hi": 130, "ap_lo": 85, "cholesterol": 1, "gluc": 1}
    bad_rows = [
        Examination(patient_id=patient.id, measured_at=NOW, **{**valid, "ap_hi": 80}),
        Examination(patient_id=patient.id, measured_at=NOW, **{**valid, "cholesterol": 4}),
        Examination(patient_id=patient.id, measured_at=NOW, risk_probability=1.5, **valid),
        Patient(full_name="Без пола", birth_date=date(1990, 1, 1), gender="X"),
    ]

    for row in bad_rows:
        db.add(row)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_db_restricts_deleting_doctor_with_appointments(db, people):
    patient, doctor = people
    db.add(_appointment(patient, doctor, datetime(2026, 11, 10, 10, 0), datetime(2026, 11, 10, 10, 30)))
    db.commit()

    db.delete(doctor)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_working_hours_are_checked_in_the_clinic_timezone(db, people):
    patient, doctor = people
    moscow = Settings(clinic_open_hour=8, clinic_close_hour=20, clinic_timezone="Europe/Moscow")
    ten_moscow = datetime(2026, 11, 10, 7, 0)  # 10:00 по Москве (UTC+3)
    late_moscow = datetime(2026, 11, 10, 17, 0)  # 20:00 по Москве — клиника уже закрыта

    assert appointments.book_appointment(db, booking(patient, doctor, ten_moscow), NOW, moscow).id
    with pytest.raises(BusinessRuleError, match="Europe/Moscow"):
        appointments.book_appointment(db, booking(patient, doctor, late_moscow), NOW, moscow)
