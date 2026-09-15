from __future__ import annotations

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.handlers.common import admit_from_tg, safe_reply, warn_rate_limited
from app.i18n import t
from app.services import captcha as captcha_svc
from app.texts import start_message_for


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    tg_user = update.effective_user
    if not message or not tg_user:
        return
    lang = ctx.user_lang(tg_user)

    if ctx.admins(context).is_admin(tg_user.id):
        await message.reply_text(t("msg.admin_hint", ctx.admin_lang(update, context)))
        return

    user, rejected = await admit_from_tg(context, tg_user)
    if user is None:
        if rejected == "rate":
            await warn_rate_limited(message, context, t("filter.muted", lang))
        return
    context.user_data.pop("mute_warned", None)
    await ctx.db(context).set_flags(user.user_id, started=True)
    settings = ctx.settings_svc(context).current

    if settings.captcha_enabled and not user.captcha_passed:
        await captcha_svc.send_challenge(message, context, tg_user)
        return

    await _send_start(message, start_message_for(settings, lang))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    tg_user = update.effective_user
    if not message:
        return
    settings = ctx.settings_svc(context).current
    lang = ctx.user_lang(tg_user) if tg_user else "zh"
    if tg_user and not ctx.admins(context).is_admin(tg_user.id):
        user, rejected = await admit_from_tg(context, tg_user)
        if user is None:
            if rejected == "rate":
                await warn_rate_limited(message, context, t("filter.muted", lang))
            return
        context.user_data.pop("mute_warned", None)
        if settings.captcha_enabled and not user.captcha_passed:
            await captcha_svc.send_challenge(message, context, tg_user)
            return
    await _send_start(message, start_message_for(settings, lang))


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return
    if not ctx.admins(context).is_admin(user.id):
        admitted, rejected = await admit_from_tg(context, user)
        if admitted is None:
            if rejected == "rate":
                await warn_rate_limited(message, context, t("filter.muted", ctx.user_lang(user)))
            return
        context.user_data.pop("mute_warned", None)
    await message.reply_text(f"ID: {user.id}")


async def _send_start(message, text: str) -> None:
    body = text or t("msg.saved", "zh")
    try:
        await message.reply_text(body, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramError:
        await safe_reply(message, body)
