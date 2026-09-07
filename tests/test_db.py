from __future__ import annotations

import asyncio
from pathlib import Path

from app.db import Database
from app.models import MATCH_CONTAINS


async def _flow(path: Path) -> None:
    db = Database(path)
    await db.init()
    try:
        user = await db.upsert_user(1, "alice", "Alice", None, "zh")
        assert user.username == "alice"
        await db.set_flags(1, started=True, captcha_passed=True)
        loaded = await db.get_user(1)
        assert loaded is not None
        assert loaded.started is True
        assert await db.find_user("@alice") is not None

        settings = await db.load_bot_settings()
        settings.captcha_enabled = True
        await db.save_bot_settings(settings)
        again = await db.load_bot_settings()
        assert again.captcha_enabled is True

        rid = await db.add_auto_reply("价格", MATCH_CONTAINS, "见价目")
        assert rid >= 1
        rules = await db.list_auto_replies()
        assert rules[0].keyword == "价格"

        await db.add_filter_keyword("加微")
        await db.add_allow_domain("example.com")
        assert await db.list_filter_keywords()
        assert await db.list_allow_domains()

        await db.add_map(
            user_id=1,
            user_chat_id=1,
            user_message_id=10,
            admin_chat_id=99,
            admin_message_id=20,
            direction="in",
        )
        mapped = await db.map_by_admin(99, 20)
        assert mapped is not None
        assert mapped.user_id == 1

        await db.incr_stat("messages_in", 2)
        stats = await db.get_stats()
        assert stats["messages_in"] == 2
    finally:
        await db.close()


def test_database_roundtrip(tmp_path: Path) -> None:
    asyncio.run(_flow(tmp_path / "bot.db"))
