import io
import pickle

import pandas as pd

from ml.config import TARGET


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def test_health_reports_model_state(client, client_with_model):
    assert client_with_model.get("/health").json() == {"status": "ok", "model_loaded": True}


def test_predict_without_model_returns_503(client, patient_record):
    response = client.post("/predict", json={"records": [patient_record]})

    assert response.status_code == 503
    assert response.json()["status"] == "error"


def test_upload_model_rejects_wrong_extension(client, model_bytes):
    response = client.post("/upload-model", files={"file": ("model.txt", model_bytes)})

    assert response.status_code == 400


def test_upload_model_rejects_corrupted_pickle(client):
    response = client.post("/upload-model", files={"file": ("model.pkl", b"not a pickle")})

    assert response.status_code == 400
    assert response.json()["status"] == "error"


def test_upload_model_rejects_non_classifier(client):
    response = client.post("/upload-model", files={"file": ("model.pkl", pickle.dumps({"a": 1}))})

    assert response.status_code == 400
    assert "predict_proba" in response.json()["detail"]


def test_upload_model_persists_file(client, model_bytes, settings):
    response = client.post("/upload-model", files={"file": ("model.pkl", model_bytes)})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["model_type"] == "LogisticRegression"
    assert body["features"] == ["age", "height", "weight", "ap_hi", "ap_lo", "cholesterol", "gluc"]
    assert settings.model_path.read_bytes() == model_bytes


def test_upload_model_respects_size_limit(client, settings):
    too_big = b"0" * (settings.max_upload_bytes + 1)

    response = client.post("/upload-model", files={"file": ("model.pkl", too_big)})

    assert response.status_code == 413


def test_predict_returns_features_and_risk(client_with_model, patient_record):
    sick = {**patient_record, "age": 23000, "ap_hi": 175, "ap_lo": 105, "cholesterol": 3}

    response = client_with_model.post("/predict", json={"records": [patient_record, sick]})

    healthy_pred, sick_pred = response.json()["predictions"]
    assert response.status_code == 200
    assert healthy_pred["cardio"] == "low_risk"
    assert sick_pred["cardio"] == "high_risk"
    assert healthy_pred["risk_probability"] < sick_pred["risk_probability"]
    assert sick_pred["ap_hi"] == 175


def test_predict_validates_input(client_with_model, patient_record):
    invalid = {**patient_record, "ap_hi": 16020, "cholesterol": 5}

    response = client_with_model.post("/predict", json={"records": [invalid]})

    fields = {error["field"] for error in response.json()["detail"]}
    assert response.status_code == 422
    assert {"body.records.0.ap_hi", "body.records.0.cholesterol"} <= fields


def test_predict_rejects_diastolic_above_systolic(client_with_model, patient_record):
    response = client_with_model.post("/predict", json={"records": [{**patient_record, "ap_lo": 130}]})

    assert response.status_code == 422
    assert "ap_lo" in response.json()["detail"][0]["message"]


def test_predict_rejects_empty_records(client_with_model):
    assert client_with_model.post("/predict", json={"records": []}).status_code == 422


def test_predict_from_raw_csv_returns_roc_auc(client_with_model, dataset):
    response = client_with_model.post("/predict-from-csv", files={"file": ("test.csv", to_csv_bytes(dataset))})

    body = response.json()
    assert response.status_code == 200
    assert body["input_format"] == "raw"
    assert body["rows"] == len(dataset)
    assert body["roc_auc"] > 0.7
    assert {"predicted_cardio", "risk_probability", "smoke"} <= body["records"][0].keys()


def test_predict_from_processed_csv(client_with_model, dataset, trained_pipeline):
    raw = dataset[trained_pipeline.feature_names_in_]
    processed = trained_pipeline[:-1].transform(raw)
    processed[TARGET] = dataset[TARGET].to_numpy()

    response = client_with_model.post("/predict-from-csv", files={"file": ("p.csv", to_csv_bytes(processed))})

    body = response.json()
    assert response.status_code == 200
    assert body["input_format"] == "processed"
    assert body["roc_auc"] is not None


def test_predict_from_csv_without_target_has_no_roc_auc(client_with_model, dataset):
    content = to_csv_bytes(dataset.drop(columns=TARGET))

    body = client_with_model.post("/predict-from-csv", files={"file": ("t.csv", content)}).json()

    assert body["roc_auc"] is None
    assert body["rows"] == len(dataset)


def test_predict_from_csv_returns_csv_file(client_with_model, dataset):
    response = client_with_model.post(
        "/predict-from-csv", params={"output": "csv"}, files={"file": ("t.csv", to_csv_bytes(dataset))}
    )

    result = pd.read_csv(io.StringIO(response.text))
    assert response.headers["content-type"].startswith("text/csv")
    assert "X-ROC-AUC" in response.headers
    assert len(result) == len(dataset)
    assert "predicted_cardio" in result.columns


def test_predict_from_csv_missing_columns(client_with_model, dataset):
    content = to_csv_bytes(dataset.drop(columns=["ap_hi"]))

    response = client_with_model.post("/predict-from-csv", files={"file": ("t.csv", content)})

    assert response.status_code == 422
    assert "ap_hi" in response.json()["detail"]


def test_predict_from_empty_csv(client_with_model):
    response = client_with_model.post("/predict-from-csv", files={"file": ("t.csv", b"")})

    assert response.status_code == 422


def test_model_info(client, client_with_model, settings):
    settings.metrics_path.write_text('{"best_model": "lr"}', encoding="utf-8")

    body = client_with_model.get("/model-info").json()

    assert body["loaded"] is True
    assert body["metrics"] == {"best_model": "lr"}


def test_autoload_model_on_startup(settings, model_bytes):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app.main import create_app

    settings.model_path.write_bytes(model_bytes)
    with TestClient(create_app(replace(settings, autoload_model=True))) as client:
        assert client.get("/health").json()["model_loaded"] is True


def test_schema_covers_production_model_features():
    import joblib
    import pytest

    from app.schemas.prediction import PatientFeatures
    from ml.config import MODEL_PATH

    if not MODEL_PATH.exists():
        pytest.skip("models/model.pkl ещё не обучена")
    features = set(joblib.load(MODEL_PATH).feature_names_in_)

    assert features <= set(PatientFeatures.model_fields)


def test_predict_from_semicolon_csv(client_with_model, dataset):
    content = dataset.to_csv(index=False, sep=";").encode()

    body = client_with_model.post("/predict-from-csv", files={"file": ("cardio_train.csv", content)}).json()

    assert body["input_format"] == "raw"
    assert body["roc_auc"] > 0.7


def test_predict_from_csv_clips_outliers(client_with_model, dataset):
    dirty = dataset.copy()
    dirty.loc[0, "ap_hi"] = 16020
    dirty.loc[1, "ap_lo"] = -70

    body = client_with_model.post("/predict-from-csv", files={"file": ("t.csv", to_csv_bytes(dirty))}).json()

    assert body["rows"] == len(dirty)
    assert all(0 <= r["risk_probability"] <= 1 for r in body["records"])
