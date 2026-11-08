from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.diagnosis import Diagnosis, appointment_diagnoses

if TYPE_CHECKING:
    from app.models.doctor import Doctor
    from app.models.patient import Patient

STATUSES = ("scheduled", "completed", "cancelled", "no_show")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled', 'completed', 'cancelled', 'no_show')", name="status_valid"),
        CheckConstraint("ends_at > scheduled_at", name="ends_after_start"),
        # Одно время у врача — один действующий приём; отменённые и неявки слот не занимают.
        Index(
            "uq_appointments_doctor_active_slot",
            "doctor_id",
            "scheduled_at",
            unique=True,
            sqlite_where=text("status IN ('scheduled', 'completed')"),
            postgresql_where=text("status IN ('scheduled', 'completed')"),
        ),
        # Поиск занятости врача по времени — самый частый запрос при записи.
        Index("ix_appointments_doctor_time", "doctor_id", "scheduled_at"),
        Index("ix_appointments_patient_time", "patient_id", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="RESTRICT"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(12), server_default="scheduled", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="appointments")
    doctor: Mapped["Doctor"] = relationship(back_populates="appointments")
    diagnoses: Mapped[list[Diagnosis]] = relationship(secondary=appointment_diagnoses, order_by=Diagnosis.icd_code)
