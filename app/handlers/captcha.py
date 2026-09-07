from __future__ import annotations

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.handlers.common import upsert_from_tg
from app.i18n import t
from app.texts import start_message_for
from app.utils import now_ts


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    tg_user = update.effective_user
    if not query or not query.data or not tg_user:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return

    token = parts[2]
    database = ctx.db(context)
    settings = ctx.settings_svc(context).current
    challenge = await database.get_captcha(tg_user.id)
    lang = ctx.user_lang(tg_user)

    if not challenge:
        await query.answer(t("captcha.expired", lang), show_alert=True)
        return

    answer, tries, expires_at = challenge
    if now_ts() > expires_at:
        await database.delete_captcha(tg_user.id)
        await query.answer(t("captcha.expired", lang), show_alert=True)
        try:
            await query.edit_message_text(t("captcha.expired", lang))
        except TelegramError:
            pass
        return

    if token == answer:
        await database.delete_captcha(tg_user.id)
        await database.set_flags(tg_user.id, captcha_passed=True, started=True)
        await database.incr_stat("captcha_pass")
        await query.answer(t("captcha.ok", lang))
        try:
            await query.edit_message_text(t("captcha.ok", lang))
        except TelegramError:
            pass
        start = start_message_for(settings, lang)
        if start and query.message:
            try:
                await query.message.reply_text(
                    start, parse_mode="HTML", disable_web_page_preview=True
                )
            except TelegramError:
                await query.message.reply_text(start)
        await upsert_from_tg(context, tg_user)
        _cancel_timeout(context, tg_user.id)
        return

    tries = await database.bump_captcha_tries(tg_user.id)
    await database.incr_stat("captcha_fail")
    if tries >= settings.captcha_max_tries:
        await database.delete_captcha(tg_user.id)
        if settings.captcha_ban_on_fail:
            await database.set_flags(tg_user.id, is_banned=True)
            await query.answer(t("captcha.fail_ban", lang), show_alert=True)
            try:
                await query.edit_message_text(t("captcha.fail_ban", lang))
            except TelegramError:
                pass
        else:
            await query.answer(t("captcha.bad", lang), show_alert=True)
            try:
                await query.edit_message_text(t("captcha.expired", lang))
            except TelegramError:
                pass
        _cancel_timeout(context, tg_user.id)
        return

    await query.answer(t("captcha.bad", lang), show_alert=True)


def _cancel_timeout(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    job_queue = context.job_queue
    if job_queue is None:
        return
    for job in job_queue.get_jobs_by_name(f"captcha:{user_id}"):
        job.schedule_removal()
