"""Оценка риска по данным осмотра с помощью загруженной ML-модели."""

from collections.abc import Iterable, Mapping
from datetime import date

import numpy as np
import pandas as pd

from app.services.model_service import ModelService

DAYS_IN_YEAR = 365.25
# В датасете пол закодирован как 1 — женщины, 2 — мужчины.
GENDER_CODES = {"F": 1, "M": 2}


def age_in_days(birth_date: date, on_date: date) -> int:
    return (on_date - birth_date).days


def build_feature_frame(rows: Iterable[Mapping]) -> pd.DataFrame:
    """Строит таблицу в формате исходного датасета: age (дни), gender (1/2), 0/1 для флагов."""
    frame = pd.DataFrame(list(rows))
    frame["gender"] = frame["gender"].map(GENDER_CODES)
    for flag in ("smoke", "alco", "active"):
        frame[flag] = frame[flag].astype(int)
    return frame


def score(model_service: ModelService, frame: pd.DataFrame) -> np.ndarray:
    """Вероятность заболевания для каждой строки. Без модели бросает ModelNotLoadedError (503)."""
    probabilities, _ = model_service.predict_proba(frame)
    return np.round(probabilities, 4)


def classify(probability: float, medium_threshold: float, high_threshold: float) -> str:
    if probability >= high_threshold:
        return "high"
    if probability >= medium_threshold:
        return "medium"
    return "low"
