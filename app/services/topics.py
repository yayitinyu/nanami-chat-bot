from __future__ import annotations

import asyncio
import logging

from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.models import User
from app.texts import user_card
from app.utils import display_name, display_text

log = logging.getLogger(__name__)

GENERAL_TOPIC_ID = 1
TOPIC_COLORS = (0x6FB9F0, 0xFFD67E, 0xCB86DB, 0x8EEE98, 0xFF93B2, 0xFB6F5F)


def topic_title(user: User) -> str:
    name = display_name(user) or str(user.user_id)
    suffix = f" (@{display_text(user.username)})" if user.username else ""
    prefix = f"{user.user_id} · "
    budget = 128 - len(prefix) - len(suffix)
    if budget < 1:
        return str(user.user_id)[:128]
    return f"{prefix}{name[:budget]}{suffix}"


def is_user_topic(thread_id: int | None) -> bool:
    return bool(thread_id) and thread_id != GENERAL_TOPIC_ID


async def inbox_is_forum(context: ContextTypes.DEFAULT_TYPE) -> bool:
    cached = context.bot_data.get("inbox_is_forum")
    if cached is not None:
        return bool(cached)
    cfg = ctx.config(context)
    if not cfg.admin_chat_id:
        context.bot_data["inbox_is_forum"] = False
        return False
    try:
        chat = await context.bot.get_chat(cfg.admin_chat_id)
        is_forum = bool(getattr(chat, "is_forum", False))
    except TelegramError:
        log.warning("cannot inspect inbox chat %s", cfg.admin_chat_id)
        is_forum = False
    context.bot_data["inbox_is_forum"] = is_forum
    return is_forum


async def topics_enabled(context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not ctx.settings_svc(context).current.forum_topics_enabled:
        return False
    if not ctx.config(context).admin_chat_id:
        return False
    return await inbox_is_forum(context)


def _lock_for(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> asyncio.Lock:
    locks: dict[int, asyncio.Lock] = context.bot_data.setdefault("topic_locks", {})
    lock = locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        locks[user_id] = lock
    return lock


async def ensure_user_topic(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    *,
    lang: str = "zh",
) -> int | None:
    if not await topics_enabled(context):
        return None
    chat_id = ctx.config(context).admin_chat_id
    if chat_id is None:
        return None
    async with _lock_for(context, user.user_id):
        fresh = await ctx.db(context).get_user(user.user_id)
        if fresh and fresh.forum_topic_id:
            return fresh.forum_topic_id
        color = TOPIC_COLORS[user.user_id % len(TOPIC_COLORS)]
        try:
            topic = await context.bot.create_forum_topic(
                chat_id,
                name=topic_title(user),
                icon_color=color,
            )
        except TelegramError:
            log.exception("failed to create forum topic for %s", user.user_id)
            return None
        thread_id = int(topic.message_thread_id)
        await ctx.db(context).set_flags(user.user_id, forum_topic_id=thread_id)
        try:
            await context.bot.send_message(
                chat_id,
                user_card(user, lang),
                parse_mode="HTML",
                message_thread_id=thread_id,
            )
        except TelegramError:
            log.warning("could not send topic intro for %s", user.user_id)
        return thread_id


async def send_to_topic(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    *,
    lang: str,
    send,
) -> int | None:
    """
    Run `send(thread_id)` and recover from closed/deleted topics.
    `send` should return a message id.
    """
    thread_id = await ensure_user_topic(context, user, lang=lang)
    if thread_id is None:
        return await send(None)
    try:
        return await send(thread_id)
    except BadRequest as exc:
        text = str(exc).lower()
        if "topic_closed" in text or "closed" in text:
            chat_id = ctx.config(context).admin_chat_id
            if chat_id:
                try:
                    await context.bot.reopen_forum_topic(chat_id, thread_id)
                    return await send(thread_id)
                except TelegramError:
                    log.warning("reopen topic %s failed", thread_id)
        if "topic" in text or "thread" in text:
            await ctx.db(context).set_flags(user.user_id, forum_topic_id=None)
            thread_id = await ensure_user_topic(context, user, lang=lang)
            if thread_id:
                try:
                    return await send(thread_id)
                except TelegramError:
                    log.exception("retry send to new topic failed")
        raise
