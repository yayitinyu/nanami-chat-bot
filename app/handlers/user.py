from __future__ import annotations

import logging

from telegram import Message, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.handlers.common import safe_reply, upsert_from_tg
from app.i18n import t
from app.models import User
from app.services import captcha as captcha_svc
from app.services.antispam import check_message
from app.services.auto_reply import match_auto_reply
from app.services.forwarding import notify_filter, relay_album, relay_user_message
from app.services.rate_limit import check_and_hit
log = logging.getLogger(__name__)


async def on_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    tg_user = update.effective_user
    if not message or not tg_user:
        return
    user = await upsert_from_tg(context, tg_user)
    await ctx.db(context).set_flags(user.user_id, started=True, is_blocked=False)

    lang = ctx.user_lang(tg_user)
    if user.is_banned:
        await safe_reply(message, t("filter.banned", lang))
        return

    settings = ctx.settings_svc(context).current
    if settings.captcha_enabled and not user.captcha_passed:
        await captcha_svc.send_challenge(message, context, tg_user)
        return

    allowed, _remain = await check_and_hit(context, user.user_id)
    if not allowed:
        if not context.user_data.get("mute_warned"):
            context.user_data["mute_warned"] = True
            await safe_reply(message, t("filter.muted", lang))
        return
    context.user_data.pop("mute_warned", None)

    if message.media_group_id:
        await _buffer_album(context, user, message)
        return

    await process_inbound(context, user, [message])


async def on_user_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.text:
        return
    database = ctx.db(context)
    maps = await database.maps_for_user_message(message.chat_id, message.message_id)
    for item in maps:
        try:
            await context.bot.edit_message_text(
                chat_id=item.admin_chat_id,
                message_id=item.admin_message_id,
                text=message.text,
            )
        except TelegramError:
            continue


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    event = update.my_chat_member
    if event is None or event.chat.type != "private":
        return
    status = event.new_chat_member.status
    user_id = event.from_user.id
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
    entry = albums.setdefault(group_id, {"user_id": user.user_id, "messages": []})
    entry["messages"].append(message)
    job_queue = context.job_queue
    if job_queue is None:
        await process_inbound(context, user, entry["messages"])
        albums.pop(group_id, None)
        return
    name = f"album:{group_id}"
    for job in job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    job_queue.run_once(flush_album, 0.8, data=group_id, name=name)


async def flush_album(context: ContextTypes.DEFAULT_TYPE) -> None:
    group_id = context.job.data if context.job else None
    albums: dict = context.bot_data.get("albums", {})
    entry = albums.pop(group_id, None)
    if not entry:
        return
    user = await ctx.db(context).get_user(entry["user_id"])
    if user is None:
        return
    await process_inbound(context, user, entry["messages"])


async def process_inbound(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    messages: list[Message],
) -> None:
    if not messages:
        return
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
        if not verdict.ok:
            await database.incr_stat("filtered")
            await notify_filter(context, user, verdict.reason or "", verdict.detail, ulang)
            if settings.notify_user_on_filter:
                reason = t(f"filter.{verdict.reason}", ulang) if verdict.reason else t("filter.fallback", ulang)
                try:
                    await messages[0].reply_text(reason)
                except TelegramError:
                    pass
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
