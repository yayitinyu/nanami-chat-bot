from __future__ import annotations

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.handlers.common import admit_global_update
from app.i18n import t
from app.services.rate_limit import check_and_hit
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
    lang = ctx.user_lang(tg_user)
    user = await database.get_user(tg_user.id)
    if user is None or user.is_banned:
        return
    if not await admit_global_update(context, consume=False):
        return
    allowed, _remaining = await check_and_hit(context, tg_user.id)
    if not allowed:
        if not context.user_data.get("captcha_mute_warned"):
            context.user_data["captcha_mute_warned"] = True
            await query.answer(t("filter.muted", lang), show_alert=True)
        return
    if not await admit_global_update(context):
        return
    context.user_data.pop("captcha_mute_warned", None)

    current = now_ts()
    outcome, _tries = await database.apply_captcha_attempt(
        tg_user.id,
        token,
        current,
        settings.captcha_max_tries,
    )
    if outcome in {"missing", "expired"}:
        await query.answer(t("captcha.expired", lang), show_alert=True)
        if outcome == "expired":
            try:
                await query.edit_message_text(t("captcha.expired", lang))
            except TelegramError:
                pass
        return

    if outcome == "wrong_type":
        await query.answer(t("captcha.pending", lang), show_alert=True)
        return

    if outcome == "passed":
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
        _cancel_timeout(context, tg_user.id)
        return

    await database.incr_stat("captcha_fail")
    if outcome == "exhausted":
        if settings.captcha_ban_on_fail:
            await database.set_flags(tg_user.id, is_banned=True)
            await query.answer(t("captcha.fail_ban", lang), show_alert=True)
            try:
                await query.edit_message_text(t("captcha.fail_ban", lang))
            except TelegramError:
                pass
        else:
            await database.set_flags(
                tg_user.id,
                muted_until=current + max(60, settings.rate_limit_mute),
            )
            context.user_data["captcha_mute_warned"] = True
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
