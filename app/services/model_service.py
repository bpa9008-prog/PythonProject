"""Хранение, загрузка и применение модели."""

import io
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from app.core.errors import InvalidInputError, InvalidModelError, ModelNotLoadedError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedModel:
    estimator: object
    # Признаки «сырых» данных — то, что ждёт пайплайн целиком.
    raw_features: list[str]
    # Признаки после предобработки — то, что ждёт финальный классификатор.
    # None, если модель не является sklearn Pipeline с предобработкой.
    processed_features: list[str] | None

    @property
    def model_type(self) -> str:
        steps = getattr(self.estimator, "steps", None)
        final = steps[-1][1] if steps else self.estimator
        return type(final).__name__


def _inspect(estimator: object) -> LoadedModel:
    if not hasattr(estimator, "predict_proba"):
        raise InvalidModelError("Объект в pkl не похож на классификатор: нет метода predict_proba.")
    raw_features = getattr(estimator, "feature_names_in_", None)
    if raw_features is None:
        raise InvalidModelError("Модель должна быть обучена на pandas.DataFrame (нет feature_names_in_).")

    processed_features = None
    steps = getattr(estimator, "steps", None)
    if steps and len(steps) > 1:
        final_features = getattr(steps[-1][1], "feature_names_in_", None)
        if final_features is not None:
            processed_features = list(final_features)

    return LoadedModel(estimator, list(raw_features), processed_features)


class ModelService:
    """Потокобезопасный контейнер текущей модели."""

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._lock = threading.Lock()
        self._model: LoadedModel | None = None

    @property
    def model(self) -> LoadedModel:
        model = self._model
        if model is None:
            raise ModelNotLoadedError()
        return model

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load_from_disk(self) -> bool:
        if not self._model_path.exists():
            logger.info("Файл модели %s не найден, сервис стартует без модели", self._model_path)
            return False
        model = _inspect(joblib.load(self._model_path))
        with self._lock:
            self._model = model
        logger.info("Модель %s загружена из %s", model.model_type, self._model_path)
        return True

    def load_from_bytes(self, content: bytes) -> LoadedModel:
        """Проверяет присланный pkl, сохраняет на диск и делает текущей моделью.

        Внимание: unpickling выполняет произвольный код — загружайте только доверенные модели.
        """
        try:
            estimator = joblib.load(io.BytesIO(content))
        except Exception as exc:
            raise InvalidModelError(f"Не удалось прочитать pkl: {exc}") from exc
        model = _inspect(estimator)

        self._model_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._model_path.with_suffix(".tmp")
        tmp_path.write_bytes(content)
        with self._lock:
            os.replace(tmp_path, self._model_path)
            self._model = model
        logger.info("Загружена новая модель %s, признаки: %s", model.model_type, model.raw_features)
        return model

    def predict_proba(self, df: pd.DataFrame) -> tuple[np.ndarray, str]:
        """Возвращает вероятность класса 1 (заболевание) и распознанный формат входа: raw или processed."""
        model = self.model
        columns = set(df.columns)

        if columns.issuperset(model.raw_features):
            return model.estimator.predict_proba(df[model.raw_features])[:, 1], "raw"

        if model.processed_features and columns.issuperset(model.processed_features):
            final_estimator = model.estimator.steps[-1][1]
            return final_estimator.predict_proba(df[model.processed_features])[:, 1], "processed"

        missing = sorted(set(model.raw_features) - columns)
        raise InvalidInputError(f"Не хватает признаков для модели: {missing}")
