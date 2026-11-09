"""Тесты на дефекты, найденные при самопроверке PR: каждый тест воспроизводит исходную проблему."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Base
from app.main import create_app
from app.services.model_service import ModelService
from tests.test_clinic_api import HEALTHY, SICK, make_diagnosis, make_patient


def make_client(settings: Settings, clock) -> TestClient:
    application = create_app(settings)
    application.state.clock = clock
    Base.metadata.create_all(application.state.engine)
    return TestClient(application)


# --- risk-followup не дублирует пациента -------------------------------------


def test_followup_lists_a_patient_once_when_examinations_share_a_timestamp(client_with_model):
    patient = make_patient(client_with_model)
    url = f"/patients/{patient['id']}/examinations"
    for _ in range(2):
        client_with_model.post(url, json={**SICK, "measured_at": "2026-11-01T09:00:00Z"})

    report = client_with_model.get("/analytics/risk-followup").json()

    assert report["total"] == 1
    assert [item["patient_id"] for item in report["items"]] == [patient["id"]]


def test_followup_uses_the_latest_examination_only(client_with_model):
    patient = make_patient(client_with_model)
    url = f"/patients/{patient['id']}/examinations"
    client_with_model.post(url, json={**SICK, "measured_at": "2026-10-01T09:00:00Z"})
    client_with_model.post(url, json={**HEALTHY, "measured_at": "2026-11-01T09:00:00Z"})

    assert client_with_model.get("/analytics/risk-followup").json()["total"] == 0


# --- проверка настроек при старте -------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"clinic_timezone": "Mars/Olympus"}, "часовой пояс"),
        ({"clinic_open_hour": 20, "clinic_close_hour": 8}, "CLINIC_OPEN_HOUR"),
        ({"clinic_close_hour": 24}, "CLINIC_CLOSE_HOUR"),
        ({"min_cancel_hours": -1}, "MIN_CANCEL_HOURS"),
        ({"risk_medium_threshold": 0.9, "risk_high_threshold": 0.5}, "RISK_MEDIUM_THRESHOLD"),
    ],
)
def test_invalid_settings_fail_at_startup(overrides, message):
    with pytest.raises(ValueError, match=message):
        Settings(**overrides)


def test_valid_non_utc_timezone_is_accepted():
    assert Settings(clinic_timezone="Europe/Moscow").clinic_timezone == "Europe/Moscow"


# --- токен загрузки модели --------------------------------------------------


@pytest.fixture
def protected_client(settings, clock):
    with make_client(replace(settings, model_upload_token="s3cret"), clock) as client:
        yield client


def upload(client, model_bytes, **headers):
    return client.post("/upload-model", files={"file": ("model.pkl", model_bytes)}, headers=headers)


def test_upload_requires_token_when_configured(protected_client, model_bytes):
    missing = upload(protected_client, model_bytes)
    wrong = upload(protected_client, model_bytes, **{"X-Upload-Token": "guess"})

    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == {"status": "error", "detail": "Для загрузки модели нужен верный заголовок X-Upload-Token"}
    assert protected_client.get("/health").json()["model_loaded"] is False


def test_upload_works_with_the_right_token(protected_client, model_bytes):
    response = upload(protected_client, model_bytes, **{"X-Upload-Token": "s3cret"})

    assert response.status_code == 200
    assert protected_client.get("/health").json()["model_loaded"] is True


def test_token_is_checked_before_the_file_is_read(protected_client):
    response = protected_client.post(
        "/upload-model", files={"file": ("model.txt", b"not a model")}, headers={"X-Upload-Token": "bad"}
    )

    assert response.status_code == 401  # а не 400 «неверное расширение»


def test_token_does_not_affect_other_endpoints(protected_client, patient_record):
    assert protected_client.get("/health").status_code == 200
    assert protected_client.post("/predict", json={"records": [patient_record]}).status_code == 503


def test_empty_token_means_upload_is_open(client, model_bytes):
    assert Settings(model_upload_token=None).model_upload_token is None
    assert upload(client, model_bytes).status_code == 200


def test_token_is_not_printed_in_settings_repr(settings):
    assert "s3cret" not in repr(replace(settings, model_upload_token="s3cret"))


# --- % и _ в поиске --------------------------------------------------------


def test_patient_search_treats_wildcards_literally(client):
    make_patient(client, full_name="Иванов")
    make_patient(client, full_name="Анна_Мария", phone="+79990001111")
    make_patient(client, full_name="Скидка 50% Петров", phone="+79990002222")

    def search(text):
        return [p["full_name"] for p in client.get("/patients", params={"search": text}).json()["items"]]

    assert search("_") == ["Анна_Мария"]
    assert search("%") == ["Скидка 50% Петров"]
    assert search("50%") == ["Скидка 50% Петров"]
    assert search("Иван") == ["Иванов"]
    assert search("\\") == []


def test_diagnosis_search_treats_wildcards_literally(client):
    make_diagnosis(client, "I10", "Гипертензия")
    make_diagnosis(client, "E11", "Диабет 2 типа")

    assert client.get("/diagnoses", params={"search": "%"}).json()["total"] == 0
    assert client.get("/diagnoses", params={"search": "_"}).json()["total"] == 0
    assert client.get("/diagnoses", params={"search": "i1"}).json()["total"] == 1


# --- запасная модель --------------------------------------------------------


def test_model_service_falls_back_to_bundled_model(tmp_path, model_bytes):
    bundled = tmp_path / "bundled.pkl"
    bundled.write_bytes(model_bytes)
    service = ModelService(tmp_path / "stored.pkl", bundled)

    assert service.load_from_disk() is True
    assert service.is_loaded


def test_model_service_without_any_model_stays_empty(tmp_path):
    service = ModelService(tmp_path / "stored.pkl", tmp_path / "bundled.pkl")

    assert service.load_from_disk() is False
    assert not service.is_loaded


def test_app_starts_with_the_bundled_model_when_nothing_is_stored(settings, clock, tmp_path, model_bytes):
    bundled = tmp_path / "bundled.pkl"
    bundled.write_bytes(model_bytes)
    configured = replace(settings, autoload_model=True, bundled_model_path=bundled)

    with make_client(configured, clock) as client:
        assert client.get("/health").json()["model_loaded"] is True


def test_uploaded_model_is_stored_at_model_path_not_at_the_bundled_one(settings, clock, tmp_path, model_bytes):
    bundled = tmp_path / "bundled.pkl"
    bundled.write_bytes(b"bundled-original")
    configured = replace(settings, bundled_model_path=bundled)

    with make_client(configured, clock) as client:
        assert upload(client, model_bytes).status_code == 200

    assert configured.model_path.read_bytes() == model_bytes
    assert bundled.read_bytes() == b"bundled-original"
