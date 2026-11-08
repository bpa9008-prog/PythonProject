"""Pydantic-схемы запросов и ответов API."""

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DAYS_IN_YEAR = 365.25


class Level(IntEnum):
    """Уровень холестерина / глюкозы, как в датасете."""

    NORMAL = 1
    ABOVE_NORMAL = 2
    WELL_ABOVE_NORMAL = 3


class PatientFeatures(BaseModel):
    """Данные пациента, нужные модели (см. input_columns в reports/metrics.json).

    Возраст передаётся в днях, как в исходном датасете: так одна и та же модель
    принимает и JSON, и сырой CSV. Индекс массы тела и возраст в годах модель считает сама.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "age": 18393,
                "height": 168,
                "weight": 62,
                "ap_hi": 110,
                "ap_lo": 80,
                "cholesterol": 1,
                "gluc": 1,
            }
        },
    )

    age: int = Field(ge=round(18 * DAYS_IN_YEAR), le=round(120 * DAYS_IN_YEAR), description="Возраст, дней")
    height: float = Field(ge=50, le=250, description="Рост, см")
    weight: float = Field(ge=10, le=300, description="Вес, кг")
    ap_hi: int = Field(ge=50, le=300, description="Систолическое (верхнее) давление, мм рт. ст.")
    ap_lo: int = Field(ge=30, le=200, description="Диастолическое (нижнее) давление, мм рт. ст.")
    cholesterol: Level = Field(description="Холестерин: 1 — норма, 2 — выше нормы, 3 — значительно выше")
    gluc: Level = Field(description="Глюкоза: 1 — норма, 2 — выше нормы, 3 — значительно выше")

    @model_validator(mode="after")
    def check_pressure(self) -> "PatientFeatures":
        if self.ap_lo > self.ap_hi:
            raise ValueError("Нижнее давление (ap_lo) не может быть больше верхнего (ap_hi)")
        return self


class PredictRequest(BaseModel):
    records: list[PatientFeatures] = Field(min_length=1, max_length=1000)


class Prediction(PatientFeatures):
    cardio: Literal["high_risk", "low_risk"]
    risk_probability: float = Field(ge=0, le=1, description="Вероятность сердечно-сосудистого заболевания")


class PredictResponse(BaseModel):
    predictions: list[Prediction]


class CsvPredictResponse(BaseModel):
    roc_auc: float | None = Field(description="Заполняется, если в CSV была колонка cardio с обоими классами")
    input_format: Literal["raw", "processed"]
    rows: int
    records: list[dict]


class UploadModelResponse(BaseModel):
    status: Literal["success"]
    message: str
    model_type: str
    features: list[str]


class ModelInfo(BaseModel):
    loaded: bool
    model_type: str | None = None
    features: list[str] = []
    metrics: dict | None = None
