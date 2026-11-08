"""Обучение и сравнение моделей, сохранение лучшей по ROC-AUC.

Запуск: python -m ml.train [--data PATH] [--model-out PATH] [--cv-folds N]
"""

import argparse
import json
import logging
from pathlib import Path

import joblib
import pandas as pd
from matplotlib.figure import Figure
from sklearn.base import ClassifierMixin
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import RocCurveDisplay, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer

from ml.config import (
    CANDIDATE_CATEGORICAL,
    CANDIDATE_NUMERIC,
    MODEL_PATH,
    RANDOM_STATE,
    RAW_DATA_PATH,
    REPORTS_DIR,
    SPLITS_DIR,
    TARGET,
    TEST_SIZE,
)
from ml.features import FeatureSelection, add_engineered_features, required_raw_columns, select_features
from ml.preprocessing import build_preprocessor, clean_dataset, load_dataset

logger = logging.getLogger(__name__)


def candidate_models() -> dict[str, ClassifierMixin]:
    return {
        "logistic_regression": LogisticRegression(max_iter=1000),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=3,
            n_jobs=-1,
            random_state=RANDOM_STATE,
        ),
        "gradient_boosting": HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=500,
            max_leaf_nodes=31,
            l2_regularization=1.0,
            random_state=RANDOM_STATE,
        ),
    }


def build_pipeline(selection: FeatureSelection, model: ClassifierMixin) -> Pipeline:
    return Pipeline(
        [
            ("features", FunctionTransformer(add_engineered_features)),
            ("preprocessor", build_preprocessor(selection.numeric, selection.categorical)),
            ("model", model),
        ]
    )


def split_dataset(df: pd.DataFrame, splits_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Делит сырые данные и сохраняет обе части — тестовая часть годится для /predict-from-csv."""
    train, test = train_test_split(df, test_size=TEST_SIZE, stratify=df[TARGET], random_state=RANDOM_STATE)
    splits_dir.mkdir(parents=True, exist_ok=True)
    train.to_csv(splits_dir / "train.csv", index=False)
    test.to_csv(splits_dir / "test.csv", index=False)
    return train, test


def save_processed_test(pipeline: Pipeline, test: pd.DataFrame, path: Path) -> None:
    # Всё, кроме классификатора: конструирование признаков + импутация, масштабирование, one-hot.
    processed = pipeline[:-1].transform(test[pipeline.feature_names_in_])
    processed[TARGET] = test[TARGET].to_numpy()
    processed.to_csv(path, index=False)


def plot_roc_curves(pipelines: dict[str, Pipeline], test: pd.DataFrame, path: Path) -> None:
    fig = Figure(figsize=(6, 6))
    ax = fig.subplots()
    for name, pipeline in pipelines.items():
        X_test = test[pipeline.feature_names_in_]
        RocCurveDisplay.from_estimator(pipeline, X_test, test[TARGET], name=name, ax=ax)
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey")
    ax.set_title("ROC-кривые на тестовой выборке")
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def train(data_path: Path, model_path: Path, reports_dir: Path, splits_dir: Path, cv_folds: int) -> dict:
    raw = load_dataset(data_path)
    raw = raw.dropna(subset=[TARGET])
    train_raw, test = split_dataset(raw, splits_dir)

    # Чистим только обучающую часть: тест остаётся «как в жизни».
    train_df, cleaning = clean_dataset(train_raw)
    logger.info("Очистка: %d -> %d строк, удалено %s", cleaning.rows_before, cleaning.rows_after, cleaning.removed)

    selection = select_features(add_engineered_features(train_df), TARGET, CANDIDATE_NUMERIC, CANDIDATE_CATEGORICAL)
    logger.info("Отобраны признаки: %s; отброшены: %s", selection.features, selection.dropped)

    # На вход модели подаём только исходные колонки, нужные для отобранных признаков:
    # они и станут контрактом модели (feature_names_in_), а остальное посчитает пайплайн.
    input_columns = required_raw_columns(selection.features)
    X_train, y_train = train_df[input_columns], train_df[TARGET]
    X_test, y_test = test[input_columns], test[TARGET]

    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=RANDOM_STATE)
    results: dict[str, dict[str, float]] = {}
    fitted: dict[str, Pipeline] = {}
    for name, model in candidate_models().items():
        pipeline = build_pipeline(selection, model)
        cv_scores = cross_val_score(pipeline, X_train, y_train, cv=cv, scoring="roc_auc")
        pipeline.fit(X_train, y_train)
        test_auc = roc_auc_score(y_test, pipeline.predict_proba(X_test)[:, 1])
        results[name] = {
            "cv_roc_auc_mean": round(float(cv_scores.mean()), 4),
            "cv_roc_auc_std": round(float(cv_scores.std()), 4),
            "test_roc_auc": round(float(test_auc), 4),
        }
        fitted[name] = pipeline
        logger.info("%s: %s", name, results[name])

    # Выбираем по кросс-валидации, чтобы тест оставался честной оценкой.
    best_name = max(results, key=lambda n: results[n]["cv_roc_auc_mean"])
    best = fitted[best_name]

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(best, model_path)
    save_processed_test(best, test, splits_dir / "test_processed.csv")

    reports_dir.mkdir(parents=True, exist_ok=True)
    plot_roc_curves(fitted, test, reports_dir / "roc_curves.png")
    metrics = {
        "best_model": best_name,
        "models": results,
        "features": selection.features,
        "input_columns": input_columns,
        "feature_scores": {k: round(v, 4) for k, v in selection.scores.items()},
        "dropped_features": selection.dropped,
        "cleaning": {"rows_before": cleaning.rows_before, "removed": cleaning.removed},
        "train_rows": len(train_df),
        "test_rows": len(test),
    }
    (reports_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Лучшая модель: %s, сохранена в %s", best_name, model_path)
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=RAW_DATA_PATH)
    parser.add_argument("--model-out", type=Path, default=MODEL_PATH)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--splits-dir", type=Path, default=SPLITS_DIR)
    parser.add_argument("--cv-folds", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    train(args.data, args.model_out, args.reports_dir, args.splits_dir, args.cv_folds)


if __name__ == "__main__":
    main()
