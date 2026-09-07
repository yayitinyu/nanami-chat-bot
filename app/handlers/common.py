from __future__ import annotations

import logging

from telegram import CallbackQuery, Message
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.models import User

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


def copied_id(result: object) -> int:
    if hasattr(result, "message_id"):
        return int(result.message_id)
    return int(result)


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


async def safe_reply(message: Message, text: str, **kwargs) -> None:
    try:
        await message.reply_text(text, **kwargs)
    except TelegramError:
        log.warning("reply failed in chat %s", message.chat_id)
