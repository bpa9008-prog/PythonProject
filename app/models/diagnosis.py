from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Связь многие-ко-многим: у приёма может быть несколько диагнозов, а один диагноз ставят многим приёмам.
appointment_diagnoses = Table(
    "appointment_diagnoses",
    Base.metadata,
    Column("appointment_id", ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True),
    Column("diagnosis_id", ForeignKey("diagnoses.id", ondelete="RESTRICT"), primary_key=True, index=True),
)


class Diagnosis(Base):
    """Справочник диагнозов по МКБ-10."""

    __tablename__ = "diagnoses"

    id: Mapped[int] = mapped_column(primary_key=True)
    icd_code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(200))
