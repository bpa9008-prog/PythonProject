"""Вспомогательные функции сервисного слоя."""

from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.schemas.common import Page, Pagination

ModelT = TypeVar("ModelT")


def commit_or_conflict(db: Session, message: str) -> None:
    """Фиксирует транзакцию; нарушение ограничения БД превращается в 409."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(message) from exc


def get_or_404(db: Session, model: type[ModelT], entity_id: int, entity: str) -> ModelT:
    obj = db.get(model, entity_id)
    if obj is None:
        raise NotFoundError(entity, entity_id)
    return obj


def paginate(db: Session, query: Select, page: Pagination) -> Page:
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    items = list(db.scalars(query.limit(page.limit).offset(page.offset)))
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)
