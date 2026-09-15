from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

from app.handlers.admin_await import await_start
from app.models import BotSettings


async def _invalid_start_message_flow() -> None:
    settings = SimpleNamespace(current=BotSettings(), update=AsyncMock())
    message = SimpleNamespace(
        text="<b>broken",
        caption=None,
        from_user=SimpleNamespace(language_code="zh"),
        reply_text=AsyncMock(side_effect=[BadRequest("bad html"), None]),
    )
    context = SimpleNamespace(
        bot_data={"settings_svc": settings},
        user_data={"await": {"action": "start"}},
    )

    await await_start(message, context, context.user_data["await"])

    settings.update.assert_not_awaited()
    assert context.user_data["await"] == {"action": "start"}
    assert message.reply_text.await_count == 2


def test_invalid_start_message_is_not_saved() -> None:
    asyncio.run(_invalid_start_message_flow())
