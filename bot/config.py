from pathlib import Path
from tempfile import gettempdir

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    bot_token: str | None = Field(default=None, alias="BOT_TOKEN")
    bot_username: str | None = Field(default=None, alias="BOT_USERNAME")
    owner_user_id: int | None = Field(default=None, alias="OWNER_USER_ID")
    ops_chat_id: int | None = Field(default=None, alias="OPS_CHAT_ID")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_to_file: bool = Field(default=False, alias="LOG_TO_FILE")
    ops_alert_level: str = Field(default="ERROR", alias="OPS_ALERT_LEVEL")
    run_mode: str = Field(default="polling", alias="RUN_MODE")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    database_pool_size: int = Field(default=20, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=40, alias="DATABASE_MAX_OVERFLOW")
    database_pool_timeout_sec: float = Field(default=30.0, alias="DATABASE_POOL_TIMEOUT_SEC")
    database_path: Path = Field(default=BASE_DIR / "data" / "kevin11.db", alias="DATABASE_PATH")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    webhook_base_url: str | None = Field(default=None, alias="WEBHOOK_BASE_URL")
    webhook_secret_token: str | None = Field(default=None, alias="WEBHOOK_SECRET_TOKEN")
    webhook_path: str = Field(default="/telegram/webhook", alias="WEBHOOK_PATH")
    webhook_host: str = Field(default="0.0.0.0", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8080, alias="WEBHOOK_PORT")
    search_limit: int = Field(default=5, alias="SEARCH_LIMIT")
    search_country: str = Field(default="IN", alias="SEARCH_COUNTRY")
    search_timeout_sec: float = Field(default=15.0, alias="SEARCH_TIMEOUT_SEC")
    metadata_cache_ttl_sec: float = Field(default=180.0, alias="METADATA_CACHE_TTL_SEC")
    resolve_cache_ttl_sec: float = Field(default=600.0, alias="RESOLVE_CACHE_TTL_SEC")
    resolve_timeout_sec: float = Field(default=20.0, alias="RESOLVE_TIMEOUT_SEC")
    resolve_attempt_timeout_sec: float = Field(default=5.0, alias="RESOLVE_ATTEMPT_TIMEOUT_SEC")
    default_quality_preset: str = Field(default="best", alias="DEFAULT_QUALITY_PRESET")
    default_audio_format: str = Field(default="mp3", alias="DEFAULT_AUDIO_FORMAT")
    message_rate_limit_count: int = Field(default=8, alias="MESSAGE_RATE_LIMIT_COUNT")
    message_rate_limit_window_sec: float = Field(default=15.0, alias="MESSAGE_RATE_LIMIT_WINDOW_SEC")
    download_timeout_sec: float = Field(default=300.0, alias="DOWNLOAD_TIMEOUT_SEC")
    resolve_concurrency: int = Field(default=16, alias="RESOLVE_CONCURRENCY")
    download_concurrency: int = Field(default=4, alias="DOWNLOAD_CONCURRENCY")
    max_audio_duration_sec: int = Field(default=1500, alias="MAX_AUDIO_DURATION_SEC")
    max_audio_size_mb: int = Field(default=49, alias="MAX_AUDIO_SIZE_MB")
    cleanup_max_age_hours: int = Field(default=8, alias="CLEANUP_MAX_AGE_HOURS")
    enable_admin_tools: bool = Field(default=True, alias="ENABLE_ADMIN_TOOLS")
    download_dir: Path = Field(default=Path(gettempdir()) / "kevin11-bot-downloads", alias="DOWNLOAD_DIR")
    data_dir: Path = BASE_DIR / "data"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator(
        "bot_token",
        "bot_username",
        "owner_user_id",
        "database_url",
        "ops_chat_id",
        "redis_url",
        "webhook_base_url",
        "webhook_secret_token",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("run_mode", mode="before")
    @classmethod
    def normalize_run_mode(cls, value: object) -> str:
        if not value:
            return "polling"
        normalized = str(value).strip().casefold()
        if normalized not in {"polling", "webhook"}:
            raise ValueError("RUN_MODE must be either 'polling' or 'webhook'.")
        return normalized

    @field_validator("search_country", mode="before")
    @classmethod
    def normalize_search_country(cls, value: object) -> str:
        if not value:
            return "IN"
        return str(value).strip().upper()

    @field_validator("webhook_path", mode="before")
    @classmethod
    def normalize_webhook_path(cls, value: object) -> str:
        if not value:
            return "/telegram/webhook"
        text = str(value).strip()
        return text if text.startswith("/") else f"/{text}"

    @field_validator("download_dir", mode="before")
    @classmethod
    def normalize_download_dir(cls, value: object) -> object:
        if value == "":
            return Path(gettempdir()) / "kevin11-bot-downloads"
        return value

    def ensure_directories(self) -> None:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        if self.log_to_file or not self.database_url:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
