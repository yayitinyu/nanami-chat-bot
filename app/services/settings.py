from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.db import Database
from app.models import BotSettings


class SettingsService:
    def __init__(self, database: Database) -> None:
        self.db = database
        self._current = BotSettings()

    @property
    def current(self) -> BotSettings:
        return self._current

    async def load(self) -> BotSettings:
        self._current = await self.db.load_bot_settings()
        return self._current

    async def save(self) -> None:
        await self.db.save_bot_settings(self._current)

    async def update(self, **changes: Any) -> BotSettings:
        for key, value in changes.items():
            if not hasattr(self._current, key):
                raise AttributeError(key)
            setattr(self._current, key, value)
        await self.save()
        return self._current

    async def toggle(self, field: str) -> bool:
        value = not bool(getattr(self._current, field))
        await self.update(**{field: value})
        return value

    async def mutate(self, mutator: Callable[[BotSettings], None]) -> BotSettings:
        mutator(self._current)
        await self.save()
        return self._current
