"""Общие зависимости эндпоинтов (Depends)."""

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.common import Pagination, pagination
from app.services.model_service import ModelService


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_model_service(request: Request) -> ModelService:
    return request.app.state.model_service


def get_now(request: Request) -> datetime:
    """Текущее время UTC. Часы лежат в app.state, чтобы тесты могли их подменить."""
    clock: Callable[[], datetime] = request.app.state.clock
    return clock()


DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ModelServiceDep = Annotated[ModelService, Depends(get_model_service)]
NowDep = Annotated[datetime, Depends(get_now)]
PageDep = Annotated[Pagination, Depends(pagination)]
