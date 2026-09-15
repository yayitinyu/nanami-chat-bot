from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import Chat, Message, MessageEntity, Update, User
from telegram.ext import ApplicationBuilder

from app.admins import AdminStore
from app.handlers import admin_menu, register, start
from app.handlers.user import on_user_edit, on_user_message


def test_edited_message_has_one_exclusive_user_route() -> None:
    application = ApplicationBuilder().token("123:ABC").build()
    register(application, AdminStore([]))
    user = User(id=7, first_name="User", is_bot=False)
    chat = Chat(id=7, type="private")
    message = Message(
        message_id=5,
        date=datetime.now(timezone.utc),
        chat=chat,
        from_user=user,
        text="edited",
    )
    update = Update(update_id=1, edited_message=message)
    handlers = application.handlers[0]
    normal = next(handler for handler in handlers if handler.callback is on_user_message)
    edited = next(handler for handler in handlers if handler.callback is on_user_edit)
    assert normal.check_update(update) is False
    assert bool(edited.check_update(update)) is True


def test_public_user_commands_are_private_chat_only() -> None:
    application = ApplicationBuilder().token("123:ABC").build()
    register(application, AdminStore([]))
    user = User(id=7, first_name="User", is_bot=False)
    message = Message(
        message_id=6,
        date=datetime.now(timezone.utc),
        chat=Chat(id=-1001, type="supergroup"),
        from_user=user,
        text="/start",
        entities=[MessageEntity(MessageEntity.BOT_COMMAND, 0, 6)],
    )
    update = Update(update_id=2, message=message)
    handler = next(
        item
        for item in application.handlers[0]
        if item.callback is start.cmd_start
    )
    assert handler.filters is not None
    assert handler.filters.check_update(update) is False


def test_edited_commands_do_not_execute_command_handlers() -> None:
    application = ApplicationBuilder().token("123:ABC").build()
    register(application, AdminStore([]))
    user = User(id=7, first_name="User", is_bot=False)
    message = Message(
        message_id=7,
        date=datetime.now(timezone.utc),
        chat=Chat(id=7, type="private"),
        from_user=user,
        text="/start",
        entities=[MessageEntity(MessageEntity.BOT_COMMAND, 0, 6)],
    )
    update = Update(update_id=3, edited_message=message)
    handler = next(
        item
        for item in application.handlers[0]
        if item.callback is start.cmd_start
    )
    assert handler.filters is not None
    assert handler.filters.check_update(update) is False

    edited = next(
        item
        for item in application.handlers[0]
        if item.callback is on_user_edit
    )
    assert bool(edited.check_update(update)) is True


async def _malformed_callback_flow() -> None:
    actor = SimpleNamespace(id=1)
    query = SimpleNamespace(
        data="u:id:not-a-number",
        from_user=actor,
        message=SimpleNamespace(chat=SimpleNamespace(id=actor.id, type="private")),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query, effective_user=actor)
    context = SimpleNamespace(
        bot_data={"admins": AdminStore([1])},
        user_data={},
    )
    await admin_menu.on_callback(update, context)
    query.answer.assert_awaited_once()


def test_malformed_admin_callback_is_ignored() -> None:
    asyncio.run(_malformed_callback_flow())


async def _unauthorized_noop_flow() -> None:
    actor = SimpleNamespace(id=2, language_code="zh")
    query = SimpleNamespace(
        data="noop",
        from_user=actor,
        message=SimpleNamespace(chat=SimpleNamespace(id=-1001, type="supergroup")),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query, effective_user=actor)
    context = SimpleNamespace(
        bot_data={
            "admins": AdminStore([1]),
            "config": SimpleNamespace(
                admin_chat_id=-1001,
                global_rate_limit_count=10,
                global_rate_limit_window=60,
            ),
            "settings_svc": SimpleNamespace(
                current=SimpleNamespace(ui_language="auto")
            ),
        },
        user_data={},
    )
    await admin_menu.on_callback(update, context)
    await admin_menu.on_callback(update, context)
    query.answer.assert_awaited_once()


def test_unauthorized_admin_callback_only_replies_once() -> None:
    asyncio.run(_unauthorized_noop_flow())
