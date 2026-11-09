"""Схемы запросов и ответов для пациентов, врачей, диагнозов, приёмов и медосмотров.

Для каждой сущности раздельно: Create (создание), Update (частичное обновление), Read (ответ).
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import UtcDatetime
from app.schemas.prediction import Level

MAX_AGE_YEARS = 120
PHONE_PATTERN = r"^\+?\d{10,15}$"


def _check_birth_date(value: date) -> date:
    today = date.today()
    if value > today:
        raise ValueError("Дата рождения не может быть в будущем")
    if (today - value).days > MAX_AGE_YEARS * 366:
        raise ValueError(f"Возраст не может превышать {MAX_AGE_YEARS} лет")
    return value


BirthDate = Annotated[date, AfterValidator(_check_birth_date)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Пациенты ---------------------------------------------------------------


class PatientCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "full_name": "Иванов Иван Иванович",
                "birth_date": "1975-04-12",
                "gender": "M",
                "phone": "+79991234567",
            }
        }
    )

    full_name: str = Field(min_length=2, max_length=200)
    birth_date: BirthDate
    gender: Literal["F", "M"]
    phone: str | None = Field(None, pattern=PHONE_PATTERN, description="Только цифры, можно с «+»")


class PatientUpdate(BaseModel):
    """Частичное обновление: передаются только изменяемые поля."""

    full_name: str | None = Field(None, min_length=2, max_length=200)
    birth_date: BirthDate | None = None
    gender: Literal["F", "M"] | None = None
    phone: str | None = Field(None, pattern=PHONE_PATTERN)


class PatientRead(ORMModel):
    id: int
    external_id: int | None
    full_name: str
    birth_date: date
    gender: Literal["F", "M"]
    phone: str | None
    created_at: datetime


# --- Врачи ------------------------------------------------------------------


class DoctorCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"full_name": "Петров Пётр Петрович", "specialty": "Кардиолог", "license_number": "MD-0001"}
        }
    )

    full_name: str = Field(min_length=2, max_length=200)
    specialty: str = Field(min_length=2, max_length=100)
    license_number: str = Field(pattern=r"^[A-Z0-9-]{4,30}$", description="Номер лицензии, например MD-0001")
    is_active: bool = True


class DoctorUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    specialty: str | None = Field(None, min_length=2, max_length=100)
    is_active: bool | None = None


class DoctorRead(ORMModel):
    id: int
    full_name: str
    specialty: str
    license_number: str
    is_active: bool


# --- Диагнозы ---------------------------------------------------------------


class DiagnosisCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"icd_code": "I10", "name": "Эссенциальная гипертензия"}})

    icd_code: str = Field(pattern=r"^[A-Z]\d{2}(\.\d{1,2})?$", description="Код МКБ-10, например I10 или I25.1")
    name: str = Field(min_length=2, max_length=200)


class DiagnosisRead(ORMModel):
    id: int
    icd_code: str
    name: str


# --- Приёмы -----------------------------------------------------------------


class AppointmentCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "patient_id": 1,
                "doctor_id": 1,
                "scheduled_at": "2026-12-01T10:00:00Z",
                "duration_minutes": 30,
                "reason": "Контроль давления",
            }
        }
    )

    patient_id: int = Field(gt=0)
    doctor_id: int = Field(gt=0)
    scheduled_at: UtcDatetime = Field(description="Начало приёма, UTC")
    duration_minutes: int = Field(30, ge=15, le=120, multiple_of=5)
    reason: str | None = Field(None, max_length=500)


class AppointmentComplete(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"diagnosis_ids": [1], "notes": "Назначен мониторинг АД"}})

    diagnosis_ids: list[int] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(None, max_length=2000)


class AppointmentRead(ORMModel):
    id: int
    patient_id: int
    doctor_id: int
    scheduled_at: datetime
    ends_at: datetime
    status: Literal["scheduled", "completed", "cancelled", "no_show"]
    reason: str | None
    notes: str | None
    diagnoses: list[DiagnosisRead]
    created_at: datetime


# --- Медосмотры -------------------------------------------------------------


class ExaminationCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "height": 172,
                "weight": 84,
                "ap_hi": 145,
                "ap_lo": 92,
                "cholesterol": 2,
                "gluc": 1,
                "smoke": False,
                "alco": False,
                "active": True,
            }
        }
    )

    measured_at: UtcDatetime | None = Field(None, description="Когда проведён осмотр, UTC; по умолчанию — сейчас")
    height: float = Field(ge=50, le=250, description="Рост, см")
    weight: float = Field(ge=10, le=300, description="Вес, кг")
    ap_hi: int = Field(ge=50, le=300, description="Верхнее давление")
    ap_lo: int = Field(ge=30, le=200, description="Нижнее давление")
    cholesterol: Level
    gluc: Level
    smoke: bool = False
    alco: bool = False
    active: bool = True

    @model_validator(mode="after")
    def check_pressure(self) -> "ExaminationCreate":
        if self.ap_lo > self.ap_hi:
            raise ValueError("Нижнее давление (ap_lo) не может быть больше верхнего (ap_hi)")
        return self


class ExaminationRead(ORMModel):
    id: int
    patient_id: int
    measured_at: datetime
    height: float
    weight: float
    ap_hi: int
    ap_lo: int
    cholesterol: int
    gluc: int
    smoke: bool
    alco: bool
    active: bool
    risk_probability: float | None
    risk_level: Literal["low", "medium", "high"] | None


# --- Аналитика --------------------------------------------------------------


class DoctorWorkload(BaseModel):
    doctor_id: int
    full_name: str
    specialty: str
    total: int
    scheduled: int
    completed: int
    cancelled: int
    no_show: int
    completion_rate: float | None = Field(description="completed / (completed + no_show); None, если приёмов не было")


class RiskDynamicsPoint(BaseModel):
    period: str = Field(description="2026-11 для month, 2026-11-08 для day, 2026 для year")
    examinations: int
    avg_risk: float
    high_risk: int
    high_risk_share: float


class TopDiagnosis(BaseModel):
    icd_code: str
    name: str
    appointments: int


class FollowupPatient(BaseModel):
    patient_id: int
    full_name: str
    measured_at: datetime
    risk_probability: float
