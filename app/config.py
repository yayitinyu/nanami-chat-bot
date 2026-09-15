from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.utils import normalize_domain, parse_telegram_user_id


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    bot_token: str = Field(min_length=1, alias="BOT_TOKEN")
    admin_ids: Annotated[list[int], NoDecode] = Field(alias="ADMIN_IDS")
    admin_chat_id: int | None = Field(default=None, alias="ADMIN_CHAT_ID")
    database_path: Path = Field(default=Path("data/bot.db"), alias="DATABASE_PATH")
    tz: str = Field(default="Asia/Shanghai", min_length=1, alias="TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    webhook_url: str | None = Field(default=None, alias="WEBHOOK_URL")
    # The process listens inside the container; Compose publishes it on loopback.
    webhook_listen: str = Field(
        default="0.0.0.0",  # nosec B104
        min_length=1,
        max_length=255,
        alias="WEBHOOK_LISTEN",
    )
    webhook_port: int = Field(default=8080, ge=1, le=65535, alias="WEBHOOK_PORT")
    webhook_path: str = Field(default="/telegram", alias="WEBHOOK_PATH")
    webhook_secret: str | None = Field(default=None, alias="WEBHOOK_SECRET")
    max_concurrent_updates: int = Field(
        default=16, ge=1, le=64, alias="MAX_CONCURRENT_UPDATES"
    )
    update_queue_size: int = Field(
        default=256, ge=16, le=10000, alias="UPDATE_QUEUE_SIZE"
    )
    webhook_max_connections: int = Field(
        default=10, ge=1, le=100, alias="WEBHOOK_MAX_CONNECTIONS"
    )
    global_rate_limit_count: int = Field(
        default=120, ge=0, le=10000, alias="GLOBAL_RATE_LIMIT_COUNT"
    )
    global_rate_limit_window: int = Field(
        default=60, ge=1, le=3600, alias="GLOBAL_RATE_LIMIT_WINDOW"
    )
    message_map_retention_days: int = Field(
        default=90, ge=1, le=3650, alias="MESSAGE_MAP_RETENTION_DAYS"
    )

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> list[int]:
        items: list[object] | None = None
        if isinstance(value, list):
            items = value
        elif isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                import json

                items = json.loads(stripped)
                if not isinstance(items, list):
                    raise ValueError("ADMIN_IDS JSON value must be a list")
            else:
                items = [p.strip() for p in stripped.split(",") if p.strip()]
        elif isinstance(value, int) and not isinstance(value, bool):
            items = [value]
        if items is None:
            raise ValueError("ADMIN_IDS must be a comma-separated list of user IDs")

        ids: list[int] = []
        for item in items:
            user_id = parse_telegram_user_id(str(item))
            if user_id is None:
                raise ValueError("ADMIN_IDS must contain positive Telegram user IDs")
            if user_id not in ids:
                ids.append(user_id)
        if not ids:
            raise ValueError("ADMIN_IDS must contain at least one user ID")
        return ids

    @field_validator("bot_token", mode="before")
    @classmethod
    def _strip_bot_token(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("BOT_TOKEN must not be empty")
        return value.strip()

    @field_validator("admin_chat_id", mode="before")
    @classmethod
    def _parse_optional_int(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @field_validator("webhook_url", "webhook_secret", mode="before")
    @classmethod
    def _empty_str_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("tz")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("TZ must be a valid IANA timezone") from exc
        return value

    @field_validator("webhook_path")
    @classmethod
    def _validate_webhook_path(cls, value: str) -> str:
        path = value.strip().strip("/")
        decoded = unquote(path)
        if (
            not path
            or len(path) > 1024
            or "\\" in path
            or "\\" in decoded
            or any(ch.isspace() or ord(ch) < 32 for ch in decoded)
        ):
            raise ValueError("WEBHOOK_PATH must be a non-empty URL path")
        return f"/{path}"

    @field_validator("webhook_secret")
    @classmethod
    def _validate_webhook_secret_chars(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", value):
            raise ValueError(
                "WEBHOOK_SECRET must be 32-256 characters using A-Z, a-z, 0-9, _ or -"
            )
        return value

    @model_validator(mode="after")
    def _validate_webhook(self) -> Config:
        if not self.webhook_url:
            return self
        parsed = urlparse(self.webhook_url)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("WEBHOOK_URL contains an invalid port") from exc
        decoded_path = unquote(parsed.path)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or not normalize_domain(self.webhook_url)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or len(parsed.path) > 1024
            or "\\" in parsed.path
            or "\\" in decoded_path
            or any(ch.isspace() or ord(ch) < 32 for ch in decoded_path)
        ):
            raise ValueError(
                "WEBHOOK_URL must be an HTTPS URL without credentials, query, "
                "fragment, or control characters"
            )
        if not self.webhook_secret:
            raise ValueError("WEBHOOK_SECRET is required when WEBHOOK_URL is set")
        return self

    @property
    def webhook_enabled(self) -> bool:
        return bool(self.webhook_url)

    @property
    def webhook_url_path(self) -> str:
        if self.webhook_url:
            path = urlparse(self.webhook_url).path
            if path and path != "/":
                return path.lstrip("/")
        return self.webhook_path.lstrip("/")

    @property
    def webhook_public_url(self) -> str | None:
        if not self.webhook_url:
            return None
        parsed = urlparse(self.webhook_url)
        if parsed.path and parsed.path != "/":
            return self.webhook_url
        return parsed._replace(path=f"/{self.webhook_url_path}").geturl()
