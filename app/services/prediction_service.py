"""Сценарии предсказания: по записям из JSON и по CSV-файлу."""

import csv
import io
import logging

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from app.core.errors import InvalidInputError
from app.schemas.prediction import CsvPredictResponse, PatientFeatures, Prediction
from app.services.model_service import ModelService

logger = logging.getLogger(__name__)

TARGET = "cardio"
PREDICTED_COLUMN = "predicted_cardio"
PROBABILITY_COLUMN = "risk_probability"


def predict_records(service: ModelService, records: list[PatientFeatures], threshold: float) -> list[Prediction]:
    df = pd.DataFrame([record.model_dump(mode="json") for record in records])
    risk, _ = service.predict_proba(df)
    return [
        Prediction(
            **record.model_dump(),
            cardio="high_risk" if p >= threshold else "low_risk",
            risk_probability=round(float(p), 4),
        )
        for record, p in zip(records, risk, strict=True)
    ]


def read_csv(content: bytes) -> pd.DataFrame:
    if not content.strip():
        raise InvalidInputError("CSV-файл пустой.")
    try:
        # sep=None — автоопределение разделителя: исходный датасет разделён «;», сплиты — «,».
        df = pd.read_csv(io.BytesIO(content), sep=None, engine="python")
    except (pd.errors.ParserError, csv.Error, UnicodeDecodeError) as exc:
        raise InvalidInputError(f"Не удалось разобрать CSV: {exc}") from exc
    if df.empty:
        raise InvalidInputError("В CSV нет строк с данными.")
    return df


def compute_roc_auc(df: pd.DataFrame, risk: np.ndarray) -> float | None:
    if TARGET not in df.columns:
        return None
    y_true = pd.to_numeric(df[TARGET], errors="coerce")
    known = y_true.notna().to_numpy()
    if y_true[known].nunique() < 2:
        logger.info("roc_auc не считается: в cardio меньше двух классов")
        return None
    return round(float(roc_auc_score(y_true[known], risk[known])), 4)


def predict_csv(service: ModelService, content: bytes, threshold: float) -> tuple[pd.DataFrame, CsvPredictResponse]:
    df = read_csv(content)
    risk, input_format = service.predict_proba(df)

    result = df.copy()
    # Кодировка как в датасете: 1 — есть заболевание (высокий риск), 0 — нет.
    result[PREDICTED_COLUMN] = (risk >= threshold).astype(int)
    result[PROBABILITY_COLUMN] = np.round(risk, 4)

    roc_auc = compute_roc_auc(df, risk)
    logger.info("CSV: %d строк, формат %s, roc_auc=%s", len(df), input_format, roc_auc)

    records = result.astype(object).where(result.notna(), None).to_dict(orient="records")
    response = CsvPredictResponse(roc_auc=roc_auc, input_format=input_format, rows=len(result), records=records)
    return result, response
