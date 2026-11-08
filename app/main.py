"""Точка входа FastAPI-приложения.

Запуск: uvicorn app.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import analytics, appointments, doctors, patients
from app.api.routes import router
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.database import create_db_engine, create_session_factory
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.services.model_service import ModelService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.model_upload_token is None:
            logger.warning(
                "MODEL_UPLOAD_TOKEN не задан: /upload-model открыт всем. Для публичного сервера задайте токен."
            )
        if settings.autoload_model:
            try:
                app.state.model_service.load_from_disk()
            except Exception:
                logger.exception("Не удалось загрузить модель при старте")
        yield
        app.state.engine.dispose()

    app = FastAPI(
        title="Cardio Clinic",
        description="Информационная система кардиологической клиники: пациенты, приёмы, медосмотры и ML-оценка риска",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.model_service = ModelService(settings.model_path)
    # Схему БД создают только миграции Alembic (alembic upgrade head), а не приложение.
    app.state.engine = create_db_engine(settings.database_url)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.clock = utcnow

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    register_error_handlers(app)
    app.include_router(router)
    for clinic_router in (patients.router, doctors.router, appointments.router, analytics.router):
        app.include_router(clinic_router)
    # Фронтенд монтируется последним, чтобы не перекрывать API-маршруты.
    if settings.frontend_dir.exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
