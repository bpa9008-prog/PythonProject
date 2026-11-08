"""Доменные ошибки и их преобразование в HTTP-ответы единого формата."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ModelNotLoadedError(ServiceError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("Модель не загружена. Загрузите её через POST /upload-model.")


class InvalidModelError(ServiceError):
    status_code = status.HTTP_400_BAD_REQUEST


class InvalidInputError(ServiceError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT


class UnauthorizedError(ServiceError):
    status_code = status.HTTP_401_UNAUTHORIZED


class NotFoundError(ServiceError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, entity: str, entity_id: int | str) -> None:
        super().__init__(f"{entity} с id={entity_id} не найден")


class ConflictError(ServiceError):
    """Операция противоречит текущему состоянию данных (занятое время, неверный статус и т. п.)."""

    status_code = status.HTTP_409_CONFLICT


class BusinessRuleError(ServiceError):
    """Запрос корректен по формату, но нарушает бизнес-правило (приём в прошлом, вне часов работы)."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT


class PayloadTooLargeError(ServiceError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE


def error_body(detail: object) -> dict:
    return {"status": "error", "detail": detail}


async def _service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
    logger.warning("%s: %s", type(exc).__name__, exc.detail)
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.detail))


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": ".".join(str(part) for part in err["loc"]), "message": err["msg"]} for err in exc.errors()]
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=error_body(errors))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ServiceError, _service_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
