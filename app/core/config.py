"""Настройки сервиса из переменных окружения."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    model_path: Path = field(default_factory=lambda: _env_path("MODEL_PATH", PROJECT_ROOT / "models" / "model.pkl"))
    # Модель, поставляемая вместе с приложением: используется, если по MODEL_PATH файла ещё нет.
    bundled_model_path: Path = field(
        default_factory=lambda: _env_path("BUNDLED_MODEL_PATH", PROJECT_ROOT / "models" / "model.pkl")
    )
    metrics_path: Path = field(
        default_factory=lambda: _env_path("METRICS_PATH", PROJECT_ROOT / "reports" / "metrics.json")
    )
    frontend_dir: Path = field(default_factory=lambda: _env_path("FRONTEND_DIR", PROJECT_ROOT / "frontend" / "public"))
    autoload_model: bool = field(default_factory=lambda: _env_bool("AUTOLOAD_MODEL", True))
    # Вероятность заболевания, начиная с которой риск считается высоким.
    risk_threshold: float = field(default_factory=lambda: float(os.getenv("RISK_THRESHOLD", "0.5")))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///clinic.db"))
    # Границы уровней риска для медосмотров: [0, medium) — low, [medium, high) — medium, от high — high.
    risk_medium_threshold: float = field(default_factory=lambda: float(os.getenv("RISK_MEDIUM_THRESHOLD", "0.4")))
    risk_high_threshold: float = field(default_factory=lambda: float(os.getenv("RISK_HIGH_THRESHOLD", "0.7")))
    # Часовой пояс клиники: в нём заданы часы работы. Время в БД и API всегда хранится в UTC.
    clinic_timezone: str = field(default_factory=lambda: os.getenv("CLINIC_TIMEZONE", "UTC"))
    clinic_open_hour: int = field(default_factory=lambda: int(os.getenv("CLINIC_OPEN_HOUR", "8")))
    clinic_close_hour: int = field(default_factory=lambda: int(os.getenv("CLINIC_CLOSE_HOUR", "20")))
    min_cancel_hours: int = field(default_factory=lambda: int(os.getenv("MIN_CANCEL_HOURS", "2")))
    # Распаковка pickle выполняет код из файла, поэтому загрузку модели можно закрыть токеном.
    model_upload_token: str | None = field(default_factory=lambda: os.getenv("MODEL_UPLOAD_TOKEN") or None, repr=False)
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "50")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    def __post_init__(self) -> None:
        """Неверные настройки должны ронять запуск сразу, а не 500-й ошибкой при первой записи на приём."""
        try:
            ZoneInfo(self.clinic_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"CLINIC_TIMEZONE={self.clinic_timezone!r}: неизвестный часовой пояс, например Europe/Moscow"
            ) from exc
        if not 0 <= self.clinic_open_hour < self.clinic_close_hour <= 23:
            raise ValueError("Часы работы: нужно 0 <= CLINIC_OPEN_HOUR < CLINIC_CLOSE_HOUR <= 23")
        if self.min_cancel_hours < 0:
            raise ValueError("MIN_CANCEL_HOURS не может быть отрицательным")
        if not 0 <= self.risk_medium_threshold <= self.risk_high_threshold <= 1:
            raise ValueError("Пороги риска: нужно 0 <= RISK_MEDIUM_THRESHOLD <= RISK_HIGH_THRESHOLD <= 1")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024
