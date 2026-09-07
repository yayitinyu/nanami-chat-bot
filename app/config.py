from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_ids: Annotated[list[int], NoDecode] = Field(alias="ADMIN_IDS")
    admin_chat_id: int | None = Field(default=None, alias="ADMIN_CHAT_ID")
    database_path: Path = Field(default=Path("data/bot.db"), alias="DATABASE_PATH")
    tz: str = Field(default="Asia/Shanghai", alias="TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    webhook_url: str | None = Field(default=None, alias="WEBHOOK_URL")
    webhook_listen: str = Field(default="0.0.0.0", alias="WEBHOOK_LISTEN")
    webhook_port: int = Field(default=8080, alias="WEBHOOK_PORT")
    webhook_path: str = Field(default="/telegram", alias="WEBHOOK_PATH")
    webhook_secret: str | None = Field(default=None, alias="WEBHOOK_SECRET")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> list[int]:
        if isinstance(value, list):
            return [int(x) for x in value]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                import json

                parsed = json.loads(stripped)
                return [int(x) for x in parsed]
            parts = [p.strip() for p in stripped.split(",") if p.strip()]
            return [int(p) for p in parts]
        if isinstance(value, int):
            return [value]
        raise ValueError("ADMIN_IDS must be a comma-separated list of integers")

    @field_validator("admin_chat_id", mode="before")
    @classmethod
    def _parse_optional_int(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @field_validator("webhook_url", "webhook_secret", mode="before")
    @classmethod
    def _empty_str_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @property
    def webhook_enabled(self) -> bool:
        return bool(self.webhook_url)

    @property
    def webhook_url_path(self) -> str:
        from urllib.parse import urlparse

        if self.webhook_url:
            path = urlparse(self.webhook_url).path
            if path and path != "/":
                return path.lstrip("/")
        return (self.webhook_path or "telegram").lstrip("/")
