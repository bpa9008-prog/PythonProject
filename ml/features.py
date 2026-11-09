"""Конструирование и отбор признаков."""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.config import COLLINEARITY_THRESHOLD, RELEVANCE_THRESHOLD
from ml.preprocessing import VALID_RANGES

DAYS_IN_YEAR = 365.25

# Из каких исходных колонок считается каждый сконструированный признак.
ENGINEERED_SOURCES = {
    "age_years": ["age"],
    "bmi": ["height", "weight"],
    "pulse_pressure": ["ap_hi", "ap_lo"],
}


def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    """Добавляет возраст в годах, индекс массы тела и пульсовое давление.

    Первый шаг пайплайна модели, поэтому работает и на обучении, и на инференсе.
    Невозможные значения прижимаются к допустимым границам: на обучении такие строки
    удалены очисткой, а на инференсе выброс не должен ломать предсказание.
    """
    df = df.copy()
    for column, (low, high) in VALID_RANGES.items():
        if column in df.columns:
            df[column] = df[column].clip(low, high)
    if "age" in df.columns:
        df["age_years"] = df["age"] / DAYS_IN_YEAR
    if {"height", "weight"} <= set(df.columns):
        df["bmi"] = df["weight"] / (df["height"] / 100) ** 2
    if {"ap_hi", "ap_lo"} <= set(df.columns):
        df["pulse_pressure"] = df["ap_hi"] - df["ap_lo"]
    return df


def required_raw_columns(features: list[str]) -> list[str]:
    """Исходные колонки, из которых получаются отобранные признаки, в порядке появления."""
    columns: list[str] = []
    for feature in features:
        for source in ENGINEERED_SOURCES.get(feature, [feature]):
            if source not in columns:
                columns.append(source)
    return columns


@dataclass
class FeatureSelection:
    numeric: list[str]
    categorical: list[str]
    scores: dict[str, float]
    dropped: dict[str, str]

    @property
    def features(self) -> list[str]:
        return self.numeric + self.categorical


def cramers_v(x: pd.Series, y: pd.Series) -> float:
    """V Крамера — сила связи двух категориальных переменных, от 0 до 1."""
    table = pd.crosstab(x, y).to_numpy()
    n = table.sum()
    min_dim = min(table.shape) - 1
    # Пустые данные или константный признак: связи нет, и делить на ноль не нужно.
    if n == 0 or min_dim <= 0:
        return 0.0
    expected = table.sum(axis=1, keepdims=True) * table.sum(axis=0, keepdims=True) / n
    chi2 = ((table - expected) ** 2 / expected).sum()
    return float(np.sqrt(chi2 / (n * min_dim)))


def _association(value: float) -> float:
    """Сила связи по модулю; NaN (константная колонка или колонка из одних пропусков) считаем отсутствием связи."""
    return 0.0 if math.isnan(value) else abs(value)


def select_features(
    df: pd.DataFrame,
    target: str,
    numeric: list[str],
    categorical: list[str],
    relevance_threshold: float = RELEVANCE_THRESHOLD,
    collinearity_threshold: float = COLLINEARITY_THRESHOLD,
) -> FeatureSelection:
    scores: dict[str, float] = {}
    dropped: dict[str, str] = {}

    for column in numeric:
        # corr() пропускает пары с NaN; если пар не осталось, получим NaN, и признак отсеется как слабый.
        scores[column] = _association(float(df[column].corr(df[target])))
    for column in categorical:
        scores[column] = cramers_v(df[column].fillna("missing"), df[target])

    relevant = [c for c in numeric + categorical if scores[c] >= relevance_threshold]
    for column in set(numeric + categorical) - set(relevant):
        dropped[column] = f"low relevance ({scores[column]:.3f} < {relevance_threshold})"

    # Из коллинеарной пары оставляем признак, сильнее связанный с таргетом.
    kept_numeric = sorted((c for c in numeric if c in relevant), key=lambda c: -scores[c])
    correlations = df[kept_numeric].corr().abs()
    selected_numeric: list[str] = []
    for column in kept_numeric:
        partner = next(
            (s for s in selected_numeric if correlations.loc[column, s] > collinearity_threshold),
            None,
        )
        if partner is None:
            selected_numeric.append(column)
        else:
            dropped[column] = f"collinear with {partner}"

    return FeatureSelection(
        numeric=[c for c in numeric if c in selected_numeric],
        categorical=[c for c in categorical if c in relevant],
        scores=scores,
        dropped=dropped,
    )
