"""Импорт всех моделей нужен, чтобы они попали в Base.metadata (Alembic, create_all)."""

from app.models.appointment import STATUSES, Appointment
from app.models.diagnosis import Diagnosis, appointment_diagnoses
from app.models.doctor import Doctor
from app.models.examination import RISK_LEVELS, Examination
from app.models.patient import Patient

__all__ = [
    "RISK_LEVELS",
    "STATUSES",
    "Appointment",
    "Diagnosis",
    "Doctor",
    "Examination",
    "Patient",
    "appointment_diagnoses",
]
