from __future__ import annotations

import logging

from telegram import Message, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.handlers.common import admit_from_tg, safe_reply, warn_rate_limited
from app.i18n import t
from app.models import User
from app.services import captcha as captcha_svc
from app.services.antispam import check_message
from app.services.auto_reply import match_auto_reply
from app.services.forwarding import notify_filter, relay_album, relay_user_message
from app.services.rate_limit import check_and_hit

log = logging.getLogger(__name__)
MAX_ALBUM_GROUPS = 100
MAX_ALBUM_ITEMS = 10
CAPTION_MEDIA_FIELDS = ("animation", "audio", "document", "photo", "video", "voice")


def has_editable_content(message: Message) -> bool:
    if message.text is not None or message.caption is not None:
        return True
    return any(getattr(message, field, None) for field in CAPTION_MEDIA_FIELDS)


async def on_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    tg_user = update.effective_user
    if not message or not tg_user:
        return
    lang = ctx.user_lang(tg_user)
    is_album = bool(message.media_group_id)
    user, rejected = await admit_from_tg(context, tg_user, hit_rate=not is_album)
    if user is None:
        if rejected == "rate":
            await warn_rate_limited(message, context, t("filter.muted", lang))
        return
    context.user_data.pop("mute_warned", None)
    await ctx.db(context).set_flags(user.user_id, started=True, is_blocked=False)

    settings = ctx.settings_svc(context).current
    if settings.captcha_enabled and not user.captcha_passed:
        await captcha_svc.send_challenge(message, context, tg_user)
        return

    if is_album:
        await _buffer_album(context, user, message)
        return

    await process_inbound(context, user, [message])


async def on_user_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    tg_user = update.effective_user
    if not message or not tg_user or not has_editable_content(message):
        return
    lang = ctx.user_lang(tg_user)
    user, rejected = await admit_from_tg(context, tg_user)
    if user is None:
        if rejected == "rate":
            await warn_rate_limited(message, context, t("filter.muted", lang))
        return
    context.user_data.pop("mute_warned", None)
    settings = ctx.settings_svc(context).current
    if settings.captcha_enabled and not user.captcha_passed:
        await captcha_svc.send_challenge(message, context, tg_user)
        return
    if not await _passes_filters(context, user, [message]):
        return
    database = ctx.db(context)
    maps = await database.editable_maps_for_user_message(message.chat_id, message.message_id)
    for item in maps:
        try:
            if message.text is not None:
                await context.bot.edit_message_text(
                    chat_id=item.admin_chat_id,
                    message_id=item.admin_message_id,
                    text=message.text,
                )
            else:
                await context.bot.edit_message_caption(
                    chat_id=item.admin_chat_id,
                    message_id=item.admin_message_id,
                    caption=message.caption,
                )
        except TelegramError:
            continue
    if maps:
        await database.incr_stat("edits_in")


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    event = update.my_chat_member
    if event is None or event.chat.type != "private":
        return
    status = event.new_chat_member.status
    user_id = event.chat.id
    database = ctx.db(context)
    if status in {"kicked", "left"}:
        await database.set_flags(user_id, is_blocked=True)
    elif status in {"member"}:
        await database.set_flags(user_id, is_blocked=False)


async def _buffer_album(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    message: Message,
) -> None:
    albums: dict = context.bot_data.setdefault("albums", {})
    group_id = message.media_group_id
    key = (message.chat_id, str(group_id))
    if key not in albums and len(albums) >= MAX_ALBUM_GROUPS:
        log.warning("album buffer full; dropping group from user %s", user.user_id)
        return
    entry = albums.setdefault(key, {"user_id": user.user_id, "messages": []})
    messages: list[Message] = entry["messages"]
    if any(item.message_id == message.message_id for item in messages):
        return
    if len(messages) >= MAX_ALBUM_ITEMS:
        return
    messages.append(message)
    job_queue = context.job_queue
    if job_queue is None:
        allowed, _remaining = await check_and_hit(context, user.user_id)
        if allowed:
            await process_inbound(context, user, messages)
        albums.pop(key, None)
        return
    name = f"album:{message.chat_id}:{group_id}"
    for job in job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    job_queue.run_once(flush_album, 0.8, data=key, name=name)


async def flush_album(context: ContextTypes.DEFAULT_TYPE) -> None:
    group_id = context.job.data if context.job else None
    albums: dict = context.bot_data.get("albums", {})
    entry = albums.pop(group_id, None)
    if not entry:
        return
    user = await ctx.db(context).get_user(entry["user_id"])
    if user is None or user.is_banned:
        return
    settings = ctx.settings_svc(context).current
    if settings.captcha_enabled and not user.captcha_passed:
        return
    allowed, _remaining = await check_and_hit(context, user.user_id)
    if not allowed:
        first = entry["messages"][0]
        await safe_reply(first, t("filter.muted", ctx.user_lang(user)))
        return
    await process_inbound(context, user, entry["messages"])


async def _passes_filters(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    messages: list[Message],
) -> bool:
    database = ctx.db(context)
    settings = ctx.settings_svc(context).current
    ulang = ctx.user_lang(user)
    keywords = [kw for _, kw in await database.list_filter_keywords()]
    domains = [d for _, d in await database.list_allow_domains()]
    for message in messages:
        verdict = check_message(
            message,
            settings,
            filter_keywords=keywords,
            allow_domains=domains,
        )
        if verdict.ok:
            continue
        await database.incr_stat("filtered")
        await notify_filter(context, user, verdict.reason or "", verdict.detail, ulang)
        if settings.notify_user_on_filter:
            reason = (
                t(f"filter.{verdict.reason}", ulang)
                if verdict.reason
                else t("filter.fallback", ulang)
            )
            await safe_reply(messages[0], reason)
        return False
    return True


async def process_inbound(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    messages: list[Message],
) -> None:
    if not messages:
        return
    database = ctx.db(context)
    ulang = ctx.user_lang(user)
    settings = ctx.settings_svc(context).current
    if not await _passes_filters(context, user, messages):
        return

    first = messages[0]
    await database.bump_message_count(user.user_id)
    await database.incr_stat("messages_in")

    note = ""
    replied = False
    if first.text or first.caption:
        rules = await database.list_auto_replies()
        rule = match_auto_reply(first.text or first.caption or "", rules)
        if rule:
            try:
                await first.reply_text(rule.reply_text, parse_mode="HTML")
            except TelegramError:
                await first.reply_text(rule.reply_text)
            replied = True
            note = t("note.auto_reply", ulang)

    if replied and settings.auto_reply_silent:
        return

    if len(messages) == 1:
        await relay_user_message(context, user, first, note=note, lang=ulang)
    else:
        await relay_album(context, user, messages, note=note, lang=ulang)
