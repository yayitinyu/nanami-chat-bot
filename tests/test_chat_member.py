from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.handlers.user import on_my_chat_member


class RecordingDb:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, bool]]] = []

    async def set_flags(self, user_id: int, **flags: bool) -> None:
        self.calls.append((user_id, flags))


async def _membership_flow() -> None:
    database = RecordingDb()
    context = SimpleNamespace(bot_data={"db": database})
    update = SimpleNamespace(
        my_chat_member=SimpleNamespace(
            chat=SimpleNamespace(id=42, type="private"),
            from_user=SimpleNamespace(id=999),
            new_chat_member=SimpleNamespace(status="kicked"),
        )
    )
    await on_my_chat_member(update, context)
    assert database.calls == [(42, {"is_blocked": True})]


def test_private_membership_tracks_chat_user_not_actor() -> None:
    asyncio.run(_membership_flow())
