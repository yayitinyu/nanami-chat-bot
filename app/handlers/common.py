from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from telegram import CallbackQuery, Message
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.models import User
from app.services.rate_limit import check_and_hit

log = logging.getLogger(__name__)

AWAIT = "await"


def set_await(context: ContextTypes.DEFAULT_TYPE, action: str, **data: object) -> None:
    context.user_data[AWAIT] = {"action": action, **data}


def get_await(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    data = context.user_data.get(AWAIT)
    return data if isinstance(data, dict) else None


def clear_await(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    data = context.user_data.pop(AWAIT, None)
    return data if isinstance(data, dict) else None


async def edit_panel(
    query: CallbackQuery,
    text: str,
    markup,
) -> None:
    try:
        await query.edit_message_text(
            text,
            reply_markup=markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        msg = str(exc).lower()
        if "not modified" in msg:
            return
        log.warning("edit_panel failed: %s", exc)


async def upsert_from_tg(context: ContextTypes.DEFAULT_TYPE, tg_user) -> User:
    database = ctx.db(context)
    return await database.upsert_user(
        tg_user.id,
        tg_user.username,
        tg_user.first_name,
        tg_user.last_name,
        tg_user.language_code,
    )


async def admit_from_tg(
    context: ContextTypes.DEFAULT_TYPE, tg_user, *, hit_rate: bool = True
) -> tuple[User | None, str | None]:
    """Return an admitted user, or a silent rejection reason."""
    database = ctx.db(context)
    existing = await database.get_user(tg_user.id)
    if existing and existing.is_banned:
        return None, "banned"
    if existing and existing.muted_until > int(time.time()):
        return None, "rate"
    if not await admit_global_update(context, consume=False):
        return None, "global_rate"
    if hit_rate:
        allowed, _remaining = await check_and_hit(context, tg_user.id)
        if not allowed:
            return None, "rate"
    if not await admit_global_update(context):
        return None, "global_rate"
    user = await upsert_from_tg(context, tg_user)
    if user.is_banned:
        return None, "banned"
    return user, None


async def admit_global_update(
    context: ContextTypes.DEFAULT_TYPE, *, consume: bool = True
) -> bool:
    """Check or consume the bounded process-wide inbound budget."""
    config = ctx.config(context)
    limit = config.global_rate_limit_count
    if limit == 0:
        return True
    window = float(config.global_rate_limit_window)
    lock = context.bot_data.get("global_rate_lock")
    if lock is None:
        lock = asyncio.Lock()
        context.bot_data["global_rate_lock"] = lock
    async with lock:
        events: deque[float] = context.bot_data.setdefault(
            "global_rate_events", deque()
        )
        current = time.monotonic()
        cutoff = current - window
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            last_log = context.bot_data.get("global_rate_last_log")
            if not isinstance(last_log, float) or current - last_log >= window:
                log.warning(
                    "global inbound update budget exhausted (%s/%ss)",
                    limit,
                    int(window),
                )
                context.bot_data["global_rate_last_log"] = current
            return False
        if consume:
            events.append(current)
        return True


async def warn_rate_limited(
    message: Message, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    if context.user_data.get("mute_warned"):
        return
    context.user_data["mute_warned"] = True
    await safe_reply(message, text)


async def safe_reply(message: Message, text: str, **kwargs) -> None:
    try:
        await message.reply_text(text, **kwargs)
    except TelegramError:
        log.warning("reply failed in chat %s", message.chat_id)
