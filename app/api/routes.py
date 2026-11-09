"""HTTP-эндпоинты сервиса."""

import hmac
import json
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, File, Header, Query, UploadFile
from fastapi.responses import Response

from app.api.deps import ModelServiceDep, SettingsDep
from app.core.config import Settings
from app.core.errors import InvalidModelError, PayloadTooLargeError, UnauthorizedError, error_body
from app.schemas.prediction import (
    CsvPredictResponse,
    ModelInfo,
    PredictRequest,
    PredictResponse,
    UploadModelResponse,
)
from app.services.prediction_service import predict_csv, predict_records

logger = logging.getLogger(__name__)

router = APIRouter()

MODEL_EXTENSIONS = (".pkl", ".joblib")
ERROR_RESPONSES = {
    401: {"description": "Неверный или отсутствующий X-Upload-Token"},
    400: {"description": "Некорректный файл", "content": {"application/json": {"example": error_body("...")}}},
    422: {"description": "Ошибка валидации входных данных"},
    503: {"description": "Модель не загружена"},
}


async def _read_upload(file: UploadFile, settings: Settings) -> bytes:
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise PayloadTooLargeError(f"Файл больше {settings.max_upload_mb} МБ.")
    return content


@router.get("/health", tags=["service"])
def health(service: ModelServiceDep) -> dict:
    return {"status": "ok", "model_loaded": service.is_loaded}


@router.get("/model-info", tags=["model"])
def model_info(service: ModelServiceDep, settings: SettingsDep) -> ModelInfo:
    metrics = None
    if settings.metrics_path.exists():
        metrics = json.loads(settings.metrics_path.read_text(encoding="utf-8"))
    if not service.is_loaded:
        return ModelInfo(loaded=False, metrics=metrics)
    model = service.model
    return ModelInfo(loaded=True, model_type=model.model_type, features=model.raw_features, metrics=metrics)


def _check_upload_token(settings: Settings, provided: str | None) -> None:
    """Если задан MODEL_UPLOAD_TOKEN, загрузка модели требует его в заголовке X-Upload-Token."""
    expected = settings.model_upload_token
    if expected is None:
        return
    if provided is None or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise UnauthorizedError("Для загрузки модели нужен верный заголовок X-Upload-Token")


@router.post("/upload-model", tags=["model"], responses=ERROR_RESPONSES)
async def upload_model(
    service: ModelServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="Обученная модель (sklearn Pipeline) в формате pkl")],
    x_upload_token: Annotated[
        str | None, Header(description="Токен загрузки; обязателен, если на сервере задан MODEL_UPLOAD_TOKEN")
    ] = None,
) -> UploadModelResponse:
    _check_upload_token(settings, x_upload_token)
    if not (file.filename or "").lower().endswith(MODEL_EXTENSIONS):
        raise InvalidModelError(f"Ожидается файл с расширением {', '.join(MODEL_EXTENSIONS)}.")
    content = await _read_upload(file, settings)
    model = service.load_from_bytes(content)
    return UploadModelResponse(
        status="success",
        message=f"Модель {file.filename} загружена",
        model_type=model.model_type,
        features=model.raw_features,
    )


@router.post("/predict", tags=["prediction"], responses=ERROR_RESPONSES)
def predict(request: PredictRequest, service: ModelServiceDep, settings: SettingsDep) -> PredictResponse:
    predictions = predict_records(service, request.records, settings.risk_threshold)
    return PredictResponse(predictions=predictions)


@router.post("/predict-from-csv", tags=["prediction"], responses=ERROR_RESPONSES)
async def predict_from_csv(
    service: ModelServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="CSV из train_test_split (сырой) или предобработанный")],
    output: Annotated[Literal["json", "csv"], Query(description="Формат ответа")] = "json",
) -> CsvPredictResponse:
    content = await _read_upload(file, settings)
    result, response = predict_csv(service, content, settings.risk_threshold)
    if output == "csv":
        headers = {"Content-Disposition": 'attachment; filename="predictions.csv"'}
        if response.roc_auc is not None:
            headers["X-ROC-AUC"] = str(response.roc_auc)
        return Response(result.to_csv(index=False), media_type="text/csv", headers=headers)
    return response
