"""Очистка данных и построение трансформера признаков."""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.config import ID_COLUMN, TARGET

# Физиологически допустимые диапазоны; всё, что вне их, — ошибки ввода.
VALID_RANGES = {
    "ap_hi": (60, 250),
    "ap_lo": (40, 200),
    "height": (120, 220),
    "weight": (30, 200),
}


@dataclass
class CleaningReport:
    """Сколько строк удалено на каждом шаге очистки."""

    rows_before: int
    removed: dict[str, int] = field(default_factory=dict)

    @property
    def rows_after(self) -> int:
        return self.rows_before - sum(self.removed.values())


def load_dataset(path: Path) -> pd.DataFrame:
    """Читает CSV с любым разделителем (исходный датасет разделён «;»)."""
    df = pd.read_csv(path, sep=None, engine="python")
    return df.drop(columns=ID_COLUMN, errors="ignore")


def _drop(df: pd.DataFrame, mask: pd.Series, reason: str, report: CleaningReport) -> pd.DataFrame:
    report.removed[reason] = int(mask.sum())
    return df.loc[~mask]


def clean_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    """Удаляет дубликаты, строки без таргета и физиологически невозможные значения.

    Пропуски в признаках не трогаем: их заполняет импьютер внутри пайплайна,
    чтобы на инференсе обрабатывались так же, как на обучении.
    """
    report = CleaningReport(rows_before=len(df))

    df = _drop(df, df.duplicated(), "duplicates", report)
    if TARGET in df.columns:
        df = _drop(df, df[TARGET].isna(), "missing_target", report)
    for column, (low, high) in VALID_RANGES.items():
        df = _drop(df, (df[column] < low) | (df[column] > high), f"{column}_outliers", report)
    df = _drop(df, df["ap_lo"] > df["ap_hi"], "ap_lo_above_ap_hi", report)

    return df.reset_index(drop=True), report


def build_preprocessor(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    """Импутация + масштабирование числовых, импутация + one-hot категориальных."""
    numeric_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    preprocessor = ColumnTransformer(
        [
            ("num", numeric_pipeline, numeric),
            ("cat", categorical_pipeline, categorical),
        ],
        verbose_feature_names_out=False,
    )
    # DataFrame на выходе: модель запоминает имена закодированных признаков,
    # и сервис может принимать уже предобработанный CSV.
    return preprocessor.set_output(transform="pandas")
