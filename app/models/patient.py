from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.examination import Examination


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (CheckConstraint("gender IN ('F', 'M')", name="gender_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Идентификатор записи в исходном датасете; по нему ETL не создаёт дубликатов.
    external_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    birth_date: Mapped[date]
    gender: Mapped[str] = mapped_column(String(1))
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="patient")
    examinations: Mapped[list["Examination"]] = relationship(back_populates="patient", cascade="all, delete-orphan")
