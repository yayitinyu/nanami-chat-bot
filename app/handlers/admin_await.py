from __future__ import annotations

import logging

from telegram import Message, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app import ctx, keyboards, texts
from app.handlers.common import clear_await, get_await, safe_reply, set_await
from app.i18n import t
from app.services.auto_reply import parse_keyword_line, valid_auto_reply_keyword
from app.services.broadcast import draft_from_message, schedule
from app.services.forwarding import copy_to_user
from app.utils import (
    display_name,
    display_text,
    escape,
    is_valid_domain,
    normalize_domain,
    parse_duration,
    parse_telegram_user_id,
)

log = logging.getLogger(__name__)


def _lang(message: Message, context: ContextTypes.DEFAULT_TYPE) -> str:
    return ctx.admin_lang_user(message.from_user, context)


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = get_await(context)
    message = update.effective_message
    if not state or not message:
        return False
    action = state.get("action")
    handler = HANDLERS.get(str(action))
    if handler is None:
        await safe_reply(message, t("msg.await", _lang(message, context)))
        return True
    await handler(message, context, state)
    return True


async def _need_text(message: Message) -> str | None:
    text = (message.text or message.caption or "").strip()
    return text or None


async def await_search(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    text = await _need_text(message)
    if not text:
        await safe_reply(message, t("msg.invalid", lang))
        return
    clear_await(context)
    user = await ctx.db(context).find_user(text)
    if user:
        await message.reply_text(
            texts.user_card(user, lang),
            parse_mode="HTML",
            reply_markup=keyboards.user_card_keyboard(user.user_id, user.is_banned, lang),
        )
        return
    users = await ctx.db(context).list_users(limit=8, search=text)
    if not users:
        await safe_reply(message, t("msg.user_not_found", lang))
        return
    rows = [
        (
            u.user_id,
            f"{display_name(u)} · @{display_text(u.username)}"
            if u.username
            else f"{display_name(u)} · {u.user_id}",
        )
        for u in users
    ]
    await message.reply_text(
        f"{t('btn.search', lang)}\n{escape(text[:256])}",
        parse_mode="HTML",
        reply_markup=keyboards.user_list_keyboard(rows, 0, 1, False, lang),
    )


async def await_user_msg(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    user_id = int(state["user_id"])
    clear_await(context)
    ok = await copy_to_user(context, user_id, message)
    await safe_reply(message, t("msg.sent" if ok else "msg.user_blocked", lang))


async def await_start(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    text = message.text or message.caption
    if not text:
        await safe_reply(message, t("msg.invalid", lang))
        return
    try:
        await message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramError:
        await safe_reply(message, t("msg.html_invalid", lang))
        return
    await ctx.settings_svc(context).update(start_message=text)
    clear_await(context)
    await safe_reply(message, t("msg.saved", lang))


async def await_ar_keyword(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    text = await _need_text(message)
    if not text:
        await safe_reply(message, t("msg.invalid", lang))
        return
    match_type, keyword = parse_keyword_line(text)
    if not valid_auto_reply_keyword(match_type, keyword):
        await safe_reply(message, t("msg.invalid", lang))
        return
    set_await(context, "ar_reply", match_type=match_type, keyword=keyword)
    await safe_reply(message, t("prompt.ar_reply", lang))


async def await_ar_reply(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    text = message.text or message.caption
    if not text:
        await safe_reply(message, t("msg.invalid", lang))
        return
    clear_await(context)
    await ctx.db(context).add_auto_reply(str(state["keyword"]), str(state["match_type"]), text)
    await safe_reply(message, t("msg.added", lang))


async def await_filter_kw(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    text = await _need_text(message)
    if not text:
        await safe_reply(message, t("msg.invalid", lang))
        return
    clear_await(context)
    ok = await ctx.db(context).add_filter_keyword(text)
    await safe_reply(message, t("msg.added" if ok else "msg.exists", lang))


async def await_domain(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    text = await _need_text(message)
    if not text:
        await safe_reply(message, t("msg.invalid", lang))
        return
    if not is_valid_domain(text):
        await safe_reply(message, t("msg.invalid", lang))
        return
    domain = normalize_domain(text)
    clear_await(context)
    ok = await ctx.db(context).add_allow_domain(domain)
    await safe_reply(message, t("msg.added" if ok else "msg.exists", lang))


async def await_rate_value(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    field = str(state.get("field"))
    text = await _need_text(message)
    if not text:
        await safe_reply(message, t("msg.invalid", lang))
        return
    if field in {"rate_limit_window", "rate_limit_mute"}:
        maximum = 86400 if field == "rate_limit_window" else 30 * 86400
        seconds = parse_duration(text, max_seconds=maximum)
        if seconds is None:
            await safe_reply(message, t("msg.duration_hint", lang))
            return
        value = seconds
    else:
        if (
            not text.isascii()
            or not text.isdigit()
            or len(text) > 3
            or not 1 <= int(text) <= 100
        ):
            await safe_reply(message, t("msg.invalid", lang))
            return
        value = int(text)
    clear_await(context)
    await ctx.settings_svc(context).update(**{field: value})
    await safe_reply(message, t("msg.saved", lang))


async def await_broadcast(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    draft = draft_from_message(message)
    if not draft["text"] and not draft["media_file_id"]:
        await safe_reply(message, t("msg.invalid", lang))
        return
    context.user_data["bc_draft"] = draft
    set_await(context, "broadcast_when")
    await message.reply_text(
        t("prompt.bc_when", lang),
        reply_markup=keyboards.broadcast_when(lang),
    )


async def await_bc_interval(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    text = await _need_text(message)
    if not text:
        await safe_reply(message, t("msg.invalid", lang))
        return
    seconds = parse_duration(text)
    if seconds is None or seconds < 60:
        await safe_reply(message, t("msg.interval_min", lang))
        return
    clear_await(context)
    await _commit_broadcast(message, context, seconds)


async def await_add_admin(message: Message, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    lang = _lang(message, context)
    text = await _need_text(message)
    if not text:
        await safe_reply(message, t("msg.invalid", lang))
        return
    user = await ctx.db(context).find_user(text)
    user_id = user.user_id if user else parse_telegram_user_id(text)
    if user_id is None:
        await safe_reply(message, t("msg.user_not_found", lang))
        return
    clear_await(context)
    if not ctx.admins(context).is_super_admin(message.from_user.id if message.from_user else None):
        await safe_reply(message, t("msg.not_admin", lang))
        return
    ok = await ctx.admins(context).add(ctx.db(context), user_id)
    await safe_reply(message, t("msg.added" if ok else "msg.exists", lang))


async def _commit_broadcast(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    interval: int | None,
    created_by: int | None = None,
) -> None:
    lang = _lang(message, context)
    draft = context.user_data.pop("bc_draft", None)
    if not isinstance(draft, dict):
        await safe_reply(message, t("msg.invalid", lang))
        return
    from app.utils import now_ts

    next_send = now_ts() + interval if interval else None
    creator = created_by
    if creator is None and message.from_user:
        creator = message.from_user.id
    item_id = await ctx.db(context).add_broadcast(
        text=draft.get("text"),
        media_file_id=draft.get("media_file_id"),
        media_type=draft.get("media_type"),
        from_chat_id=draft.get("from_chat_id"),
        from_message_id=draft.get("from_message_id"),
        interval_seconds=interval,
        next_send_at=next_send,
        created_by=creator,
        is_enabled=bool(interval),
    )
    item = await ctx.db(context).get_broadcast(item_id)
    if item and interval:
        schedule(context.application, item)
        await safe_reply(message, t("bc.created", lang, id=item_id))
        return
    if item:
        from app.services.broadcast import deliver

        await deliver(context, item, notify_chat_id=message.chat_id, lang=lang)
    else:
        await safe_reply(message, t("msg.invalid", lang))


HANDLERS = {
    "search": await_search,
    "user_msg": await_user_msg,
    "start": await_start,
    "ar_keyword": await_ar_keyword,
    "ar_reply": await_ar_reply,
    "filter_kw": await_filter_kw,
    "domain": await_domain,
    "rate_value": await_rate_value,
    "broadcast": await_broadcast,
    "bc_interval": await_bc_interval,
    "add_admin": await_add_admin,
}
