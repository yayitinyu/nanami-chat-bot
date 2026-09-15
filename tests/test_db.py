from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

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
        await db.set_flags(1, notes="keep", forum_topic_id=44)
        await db.set_flags(1, notes=None)
        loaded = await db.get_user(1)
        assert loaded is not None
        assert loaded.started is True
        assert loaded.notes is None
        assert loaded.forum_topic_id == 44
        with pytest.raises(ValueError, match="unknown user flag"):
            await db.set_flags(1, unknown=True)
        assert await db.find_user("@alice") is not None
        assert [item.user_id for item in await db.list_users(search="ali")] == [1]
        assert await db.count_users(search="ali") == 1
        assert await db.list_users(banned_only=True) == []
        assert await db.count_users(active_only=True) == 1
        await db.set_flags(1, is_banned=True)
        assert [item.user_id for item in await db.list_users(banned_only=True)] == [1]
        assert await db.count_users(active_only=True) == 0
        await db.set_flags(1, is_banned=False)

        settings = await db.load_bot_settings()
        settings.captcha_enabled = True
        await db.save_bot_settings(settings)
        again = await db.load_bot_settings()
        assert again.captcha_enabled is True

        await db.set_setting(
            "extra_admin_ids",
            '[2, "3", -1, true, "99999999999999999999", 2]',
        )
        assert await db.extra_admin_ids() == [2, 3]

        rid = await db.add_auto_reply("价格", MATCH_CONTAINS, "见价目")
        assert rid >= 1
        rules = await db.list_auto_replies()
        assert rules[0].keyword == "价格"

        await db.add_filter_keyword("加微")
        await db.add_allow_domain("example.com")
        assert await db.list_filter_keywords()
        assert await db.list_allow_domains()

        indexes = await db.fetchall("PRAGMA index_list(rate_events)")
        assert "idx_rate_ts" in {str(row["name"]) for row in indexes}
        indexes = await db.fetchall("PRAGMA index_list(captcha_challenges)")
        assert "idx_captcha_expires" in {str(row["name"]) for row in indexes}

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

        await db.add_map(
            user_id=1,
            user_chat_id=1,
            user_message_id=10,
            admin_chat_id=99,
            admin_message_id=21,
            direction="in",
        )
        editable = await db.editable_maps_for_user_message(1, 10)
        assert [item.admin_message_id for item in editable] == [21]
        await db.execute("UPDATE message_map SET created_at=1")
        assert await db.prune_message_maps(2) == 2
        assert await db.editable_maps_for_user_message(1, 10) == []

        await db.incr_stat("messages_in", 2)
        stats = await db.get_stats()
        assert stats["messages_in"] == 2
    finally:
        await db.close()


def test_database_roundtrip(tmp_path: Path) -> None:
    asyncio.run(_flow(tmp_path / "bot.db"))


async def _concurrent_rate_flow(path: Path) -> None:
    db = Database(path)
    await db.init()
    try:
        await db.upsert_user(7, "burst", "Burst", None, "en")
        results = await asyncio.gather(
            *[
                db.admit_rate_event(
                    7,
                    ts=1000,
                    enabled=True,
                    window=30,
                    limit=1,
                    mute=300,
                    prune_before=0,
                )
                for _ in range(20)
            ]
        )
        assert sum(1 for allowed, _ in results if allowed) == 1
        assert await db.count_rate_events(7, 970) == 1
    finally:
        await db.close()


def test_rate_admission_is_atomic(tmp_path: Path) -> None:
    asyncio.run(_concurrent_rate_flow(tmp_path / "rate.db"))


async def _captcha_flow(path: Path) -> None:
    db = Database(path)
    await db.init()
    try:
        await db.upsert_user(9, "captcha", "Captcha", None, "en")
        assert await db.create_captcha_if_absent(9, "winner", 200, 100)
        assert not await db.create_captcha_if_absent(9, "other", 200, 100)
        assert await db.apply_captcha_attempt(9, "wrong", 100, 3) == ("failed", 1)
        assert await db.apply_captcha_attempt(9, "winner", 100, 3) == ("passed", 1)
        assert await db.apply_captcha_attempt(9, "winner", 100, 3) == ("missing", 0)
        user = await db.get_user(9)
        assert user is not None and user.captcha_passed

        assert await db.create_captcha_if_absent(9, "old", 300, 200)
        assert not await db.delete_captcha_if_matches(9, "new", 300)
        assert await db.delete_captcha_if_matches(9, "old", 300)
        assert await db.create_captcha_if_absent(9, "expired", 400, 300)
        assert await db.prune_expired_captchas(400) == 1
    finally:
        await db.close()


def test_captcha_state_transitions_are_atomic(tmp_path: Path) -> None:
    asyncio.run(_captcha_flow(tmp_path / "captcha.db"))


async def _failed_commit_rolls_back(path: Path) -> None:
    db = Database(path)
    connection = AsyncMock()
    connection.execute.return_value = AsyncMock()
    connection.commit.side_effect = RuntimeError("commit failed")
    db._conn = connection  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="commit failed"):
        await db.execute("UPDATE users SET started=1")
    connection.rollback.assert_awaited_once()


def test_failed_write_commit_rolls_back(tmp_path: Path) -> None:
    asyncio.run(_failed_commit_rolls_back(tmp_path / "unused.db"))
