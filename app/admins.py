from __future__ import annotations

import asyncio

from telegram import Message
from telegram.ext.filters import MessageFilter

from app.db import Database


class AdminStore:
    def __init__(self, env_ids: list[int]) -> None:
        self.env_ids = set(env_ids)
        self.extra_ids: set[int] = set()
        self._lock = asyncio.Lock()

    @property
    def all_ids(self) -> set[int]:
        return self.env_ids | self.extra_ids

    def is_admin(self, user_id: int | None) -> bool:
        return bool(user_id) and user_id in self.all_ids

    def is_super_admin(self, user_id: int | None) -> bool:
        return bool(user_id) and user_id in self.env_ids

    async def load(self, database: Database) -> None:
        self.extra_ids = set(await database.extra_admin_ids())

    async def add(self, database: Database, user_id: int) -> bool:
        async with self._lock:
            if user_id in self.all_ids:
                return False
            candidate = self.extra_ids | {user_id}
            await database.set_extra_admin_ids(sorted(candidate))
            self.extra_ids = candidate
            return True

    async def remove(self, database: Database, user_id: int) -> bool:
        async with self._lock:
            if user_id in self.env_ids or user_id not in self.extra_ids:
                return False
            candidate = self.extra_ids - {user_id}
            await database.set_extra_admin_ids(sorted(candidate))
            self.extra_ids = candidate
            return True


class AdminFilter(MessageFilter):
    def __init__(self, store: AdminStore) -> None:
        super().__init__()
        self.store = store

    def filter(self, message: Message) -> bool:
        user = message.from_user
        return bool(user and self.store.is_admin(user.id))
