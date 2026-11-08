from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.patient import Patient

RISK_LEVELS = ("low", "medium", "high")


class Examination(Base):
    """Результат медосмотра с оценкой риска от ML-модели."""

    __tablename__ = "examinations"
    __table_args__ = (
        CheckConstraint("ap_hi >= ap_lo", name="pressure_order"),
        CheckConstraint("cholesterol IN (1, 2, 3)", name="cholesterol_valid"),
        CheckConstraint("gluc IN (1, 2, 3)", name="gluc_valid"),
        CheckConstraint("height > 0 AND weight > 0", name="body_positive"),
        CheckConstraint("risk_probability IS NULL OR risk_probability BETWEEN 0 AND 1", name="risk_range"),
        CheckConstraint("risk_level IS NULL OR risk_level IN ('low', 'medium', 'high')", name="risk_level_valid"),
        Index("ix_examinations_patient_time", "patient_id", "measured_at"),
        Index("ix_examinations_measured_at", "measured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    measured_at: Mapped[datetime] = mapped_column(DateTime)
    height: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    ap_hi: Mapped[int] = mapped_column(Integer)
    ap_lo: Mapped[int] = mapped_column(Integer)
    cholesterol: Mapped[int] = mapped_column(Integer)
    gluc: Mapped[int] = mapped_column(Integer)
    smoke: Mapped[bool] = mapped_column(Boolean, default=False)
    alco: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    risk_probability: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(6), index=True)

    patient: Mapped["Patient"] = relationship(back_populates="examinations")
