import io
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

from app.core.config import Settings
from app.core.database import Base
from app.main import create_app
from ml.config import ID_COLUMN, RAW_CATEGORICAL, RAW_NUMERIC, TARGET
from ml.features import FeatureSelection, required_raw_columns
from ml.train import build_pipeline

SELECTION = FeatureSelection(
    numeric=["age_years", "bmi", "ap_hi", "ap_lo"],
    categorical=["cholesterol", "gluc"],
    scores={},
    dropped={},
)


def make_dataset(n_rows: int = 400, seed: int = 0) -> pd.DataFrame:
    """Синтетический датасет со схемой cardio_train и зависимым от давления и возраста таргетом."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            ID_COLUMN: np.arange(n_rows),
            "age": rng.integers(30 * 365, 65 * 365, n_rows),
            "gender": rng.choice([1, 2], n_rows),
            "height": rng.integers(150, 195, n_rows),
            "weight": rng.uniform(50, 120, n_rows).round(1),
            "ap_hi": rng.integers(100, 180, n_rows),
            "cholesterol": rng.choice([1, 2, 3], n_rows, p=[0.7, 0.2, 0.1]),
            "gluc": rng.choice([1, 2, 3], n_rows, p=[0.8, 0.1, 0.1]),
            "smoke": rng.choice([0, 1], n_rows),
            "alco": rng.choice([0, 1], n_rows),
            "active": rng.choice([0, 1], n_rows),
        }
    )
    df["ap_lo"] = df["ap_hi"] - rng.integers(30, 50, n_rows)
    risk = (df["ap_hi"] - 130) / 15 + (df["age"] / 365 - 50) / 10 + df["cholesterol"] + rng.normal(0, 0.7, n_rows)
    df[TARGET] = (risk > np.median(risk)).astype(int)
    return df[[ID_COLUMN, *RAW_NUMERIC, *RAW_CATEGORICAL, TARGET]]


@pytest.fixture(scope="session")
def dataset() -> pd.DataFrame:
    return make_dataset()


@pytest.fixture(scope="session")
def trained_pipeline(dataset: pd.DataFrame):
    pipeline = build_pipeline(SELECTION, LogisticRegression(max_iter=1000))
    return pipeline.fit(dataset[required_raw_columns(SELECTION.features)], dataset[TARGET])


@pytest.fixture(scope="session")
def model_bytes(trained_pipeline) -> bytes:
    buffer = io.BytesIO()
    joblib.dump(trained_pipeline, buffer)
    return buffer.getvalue()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        model_path=tmp_path / "model.pkl",
        metrics_path=tmp_path / "metrics.json",
        frontend_dir=tmp_path / "no-frontend",
        autoload_model=False,
        max_upload_mb=1,
        database_url="sqlite://",  # отдельная БД в памяти на каждый тест — откат между тестами не нужен
    )


class FakeClock:
    """Управляемые часы: тест сам решает, «который сейчас час»."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 9, 9, 0))  # понедельник, 09:00 UTC


@pytest.fixture
def app(settings: Settings, clock: FakeClock):
    application = create_app(settings)
    application.state.clock = clock
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(app):
    with app.state.session_factory() as session:
        yield session


@pytest.fixture
def client_with_model(client: TestClient, model_bytes: bytes) -> TestClient:
    response = client.post("/upload-model", files={"file": ("model.pkl", model_bytes)})
    assert response.status_code == 200
    return client


@pytest.fixture
def patient_record() -> dict:
    return {
        "age": 18393,
        "height": 168,
        "weight": 62,
        "ap_hi": 110,
        "ap_lo": 80,
        "cholesterol": 1,
        "gluc": 1,
    }
