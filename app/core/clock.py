from datetime import UTC, datetime


def utcnow() -> datetime:
    """Текущее время в UTC без часового пояса — так время хранится в БД."""
    return datetime.now(UTC).replace(tzinfo=None)
