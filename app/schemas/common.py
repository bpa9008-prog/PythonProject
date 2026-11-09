"""Общие типы схем: пагинация и нормализация времени."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import AfterValidator, BaseModel

T = TypeVar("T")


def to_naive_utc(value: datetime) -> datetime:
    """Время хранится в UTC без часового пояса; смещение из запроса учитывается и отбрасывается."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


UtcDatetime = Annotated[datetime, AfterValidator(to_naive_utc)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=100, description="Сколько записей вернуть")] = 20,
    offset: Annotated[int, Query(ge=0, description="Сколько записей пропустить")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)
