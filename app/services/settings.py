from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from app.db import Database
from app.models import BotSettings


class SettingsService:
    def __init__(self, database: Database) -> None:
        self.db = database
        self._current = BotSettings()
        self._lock = asyncio.Lock()

    @property
    def current(self) -> BotSettings:
        return self._current

    async def load(self) -> BotSettings:
        async with self._lock:
            self._current = await self.db.load_bot_settings()
            return self._current

    async def update(self, **changes: Any) -> BotSettings:
        async with self._lock:
            candidate = deepcopy(self._current)
            for key, value in changes.items():
                if not hasattr(candidate, key):
                    raise AttributeError(key)
                setattr(candidate, key, value)
            await self.db.save_bot_settings(candidate)
            self._current = candidate
            return self._current

    async def toggle(self, field: str) -> bool:
        async with self._lock:
            candidate = deepcopy(self._current)
            value = not bool(getattr(candidate, field))
            setattr(candidate, field, value)
            await self.db.save_bot_settings(candidate)
            self._current = candidate
            return value

    async def mutate(self, mutator: Callable[[BotSettings], None]) -> BotSettings:
        async with self._lock:
            candidate = deepcopy(self._current)
            mutator(candidate)
            await self.db.save_bot_settings(candidate)
            self._current = candidate
            return self._current
