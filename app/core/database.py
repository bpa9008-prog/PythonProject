"""Подключение к БД: engine, фабрика сессий и базовый класс моделей."""

from sqlalchemy import Engine, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Явные имена ограничений нужны, чтобы Alembic мог их удалять при downgrade.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_db_engine(url: str) -> Engine:
    kwargs: dict = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            # In-memory БД живёт в одном соединении, иначе каждая сессия увидит пустую базу.
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _):
            # В SQLite внешние ключи по умолчанию не проверяются.
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
