import json

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline

from ml.config import CANDIDATE_CATEGORICAL, ID_COLUMN, TARGET
from ml.features import add_engineered_features, cramers_v, required_raw_columns, select_features
from ml.preprocessing import build_preprocessor, clean_dataset, load_dataset
from ml.train import split_pipeline, train
from tests.conftest import make_dataset


def test_load_dataset_reads_semicolon_csv_and_drops_id(tmp_path, dataset):
    path = tmp_path / "cardio_train.csv"
    dataset.to_csv(path, sep=";", index=False)

    loaded = load_dataset(path)

    assert ID_COLUMN not in loaded.columns
    assert len(loaded) == len(dataset)


def test_clean_dataset_removes_duplicates_and_outliers(dataset):
    df = dataset.drop(columns=ID_COLUMN)
    dirty = pd.concat([df, df.head(3)], ignore_index=True)
    dirty.loc[10, "ap_hi"] = 16020
    dirty.loc[11, "height"] = 55
    dirty.loc[12, ["ap_hi", "ap_lo"]] = [100, 150]

    cleaned, report = clean_dataset(dirty)

    assert report.removed["duplicates"] == 3
    assert report.removed["ap_hi_outliers"] == 1
    assert report.removed["height_outliers"] == 1
    assert report.removed["ap_lo_above_ap_hi"] == 1
    assert len(cleaned) == report.rows_after
    assert (cleaned["ap_lo"] <= cleaned["ap_hi"]).all()


def test_engineered_features():
    df = pd.DataFrame({"age": [18262], "height": [180], "weight": [81], "ap_hi": [130], "ap_lo": [85]})

    result = add_engineered_features(df)

    assert result.loc[0, "age_years"] == pytest.approx(50, abs=0.01)
    assert result.loc[0, "bmi"] == pytest.approx(25.0)
    assert result.loc[0, "pulse_pressure"] == 45
    assert "bmi" not in df.columns


def test_engineered_features_clip_impossible_values():
    df = pd.DataFrame({"ap_hi": [16020, -150], "ap_lo": [80, -70]})

    result = add_engineered_features(df)

    assert result["ap_hi"].tolist() == [250, 60]
    assert result["ap_lo"].tolist() == [80, 40]


def test_required_raw_columns_expands_engineered_features():
    columns = required_raw_columns(["age_years", "bmi", "ap_hi", "cholesterol"])

    assert columns == ["age", "height", "weight", "ap_hi", "cholesterol"]


def test_preprocessor_imputes_and_encodes(dataset):
    df = add_engineered_features(dataset)
    df.loc[:5, "bmi"] = np.nan
    preprocessor = build_preprocessor(["bmi", "ap_hi"], ["cholesterol"])

    transformed = preprocessor.fit_transform(df)

    assert not transformed.isna().any().any()
    assert {"cholesterol_1", "cholesterol_3"} <= set(transformed.columns)
    assert abs(transformed["ap_hi"].mean()) < 1e-6


def test_cramers_v_bounds():
    x = pd.Series(list("aabb") * 25)

    assert cramers_v(x, x) > 0.95
    assert cramers_v(x, pd.Series([0, 1] * 50)) < 0.05


def test_select_features_drops_noise_and_collinear():
    df = make_dataset(n_rows=5000, seed=7)
    df["noise"] = np.random.default_rng(1).normal(size=len(df))
    df["ap_hi_doubled"] = df["ap_hi"] * 2 + 1

    selection = select_features(df, TARGET, ["noise", "ap_hi", "ap_hi_doubled", "age"], CANDIDATE_CATEGORICAL)

    assert selection.numeric in (["ap_hi", "age"], ["ap_hi_doubled", "age"])
    assert selection.dropped["noise"].startswith("low relevance")
    assert any(reason.startswith("collinear with ap_hi") for reason in selection.dropped.values())
    assert "smoke" in selection.dropped
    assert "cholesterol" in selection.categorical


def test_train_saves_best_model_and_metrics(tmp_path):
    data_path = tmp_path / "data.csv"
    make_dataset(n_rows=600, seed=3).to_csv(data_path, sep=";", index=False)

    metrics = train(data_path, tmp_path / "model.pkl", tmp_path / "reports", tmp_path / "splits", cv_folds=3)

    model = joblib.load(tmp_path / "model.pkl")
    saved = json.loads((tmp_path / "reports" / "metrics.json").read_text(encoding="utf-8"))
    assert set(metrics["models"]) == {"logistic_regression", "random_forest", "gradient_boosting"}
    assert saved["best_model"] == metrics["best_model"]
    assert list(model.feature_names_in_) == metrics["input_columns"]
    assert TARGET not in model.feature_names_in_
    assert (tmp_path / "reports" / "roc_curves.png").exists()
    assert {"train.csv", "test.csv", "test_processed.csv"} <= {p.name for p in (tmp_path / "splits").iterdir()}


# --- защиты, добавленные после ревью -----------------------------------------


def test_cramers_v_returns_zero_for_empty_input_without_warnings(recwarn):
    assert cramers_v(pd.Series([], dtype=object), pd.Series([], dtype=int)) == 0.0
    assert len(recwarn) == 0  # раньше здесь были RuntimeWarning из-за деления на ноль


def test_cramers_v_returns_zero_for_a_constant_feature():
    assert cramers_v(pd.Series(["a"] * 10), pd.Series([0, 1] * 5)) == 0.0


def test_select_features_scores_an_all_nan_column_as_no_relationship(dataset):
    df = dataset.copy()
    df["empty"] = np.nan

    selection = select_features(df, TARGET, ["empty", "ap_hi"], [])

    assert selection.scores["empty"] == 0.0
    assert selection.dropped["empty"].startswith("low relevance")
    assert selection.numeric == ["ap_hi"]


def test_select_features_ignores_nan_pairs_instead_of_failing(dataset):
    df = dataset.copy()
    df.loc[df.index[:50], "ap_hi"] = np.nan

    selection = select_features(df, TARGET, ["ap_hi"], [])

    assert 0 < selection.scores["ap_hi"] <= 1
    assert selection.numeric == ["ap_hi"]


def test_split_pipeline_separates_preprocessing_from_the_classifier(trained_pipeline):
    preprocessing, model = split_pipeline(trained_pipeline)

    assert type(model).__name__ == "LogisticRegression"
    assert [name for name, _ in preprocessing.steps] == ["features", "preprocessor"]


def test_split_pipeline_rejects_a_renamed_or_reordered_final_step(trained_pipeline):
    *steps, (_, classifier) = trained_pipeline.steps
    renamed = Pipeline([*steps, ("clf", classifier)])

    with pytest.raises(ValueError, match="model"):
        split_pipeline(renamed)
