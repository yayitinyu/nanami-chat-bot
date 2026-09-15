from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.i18n import t
from app.services.turnstile import (
    TURNSTILE_KIND,
    build_challenge_url,
    new_challenge_token,
)
from app.utils import now_ts

if TYPE_CHECKING:
    from telegram import User as TgUser

DECOYS = ("✗", "×", "•", "○", "□", "△")
RNG = secrets.SystemRandom()


def _button(label: str, token: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=f"c:x:{token}")


def build_button_challenge() -> tuple[str, InlineKeyboardMarkup]:
    winner = secrets.token_hex(4)
    options = [("✓", winner)]
    used_labels = {"✓"}
    while len(options) < 4:
        decoy = secrets.choice(DECOYS)
        if decoy in used_labels:
            continue
        used_labels.add(decoy)
        options.append((decoy, secrets.token_hex(4)))
    RNG.shuffle(options)
    markup = InlineKeyboardMarkup([[_button(label, token)] for label, token in options])
    return winner, markup


def build_math_challenge(lang: str = "zh") -> tuple[str, InlineKeyboardMarkup, str]:
    a = RNG.randint(2, 9)
    b = RNG.randint(2, 9)
    correct = a + b
    winner = secrets.token_hex(4)
    choices = {correct}
    while len(choices) < 4:
        delta = secrets.choice([-4, -3, -2, -1, 1, 2, 3, 4, 5])
        choices.add(max(1, correct + delta))
    ordered = list(choices)
    RNG.shuffle(ordered)
    rows = []
    for value in ordered:
        token = winner if value == correct else secrets.token_hex(4)
        rows.append([_button(str(value), token)])
    prompt = t("captcha.math", lang, a=a, b=b)
    return winner, InlineKeyboardMarkup(rows), prompt


async def send_challenge(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    user: TgUser,
) -> bool:
    database = ctx.db(context)
    settings = ctx.settings_svc(context).current
    lang = ctx.user_lang(user)
    kind = "legacy"
    if settings.captcha_type == "turnstile":
        config = ctx.config(context)
        if not config.turnstile_configured or not config.challenge_public_url:
            try:
                await message.reply_text(t("captcha.unavailable", lang))
            except TelegramError:
                pass
            return False
        answer = new_challenge_token()
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        t("captcha.open", lang),
                        url=build_challenge_url(config.challenge_public_url, answer),
                    )
                ]
            ]
        )
        prompt = t("captcha.turnstile", lang)
        kind = TURNSTILE_KIND
    elif settings.captcha_type == "math":
        answer, markup, prompt = build_math_challenge(lang)
    else:
        answer, markup = build_button_challenge()
        prompt = t("captcha.button", lang)
    current = now_ts()
    expires = current + settings.captcha_timeout
    created = await database.create_captcha_if_absent(
        user.id,
        answer,
        expires,
        current,
        kind=kind,
    )
    if not created:
        return False
    try:
        sent = await message.reply_text(prompt, reply_markup=markup)
    except TelegramError:
        await database.delete_captcha_if_matches(user.id, answer, expires)
        return False
    job_queue = context.job_queue
    if job_queue is not None:
        name = f"captcha:{user.id}"
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()
        job_queue.run_once(
            captcha_timeout,
            when=settings.captcha_timeout,
            data={
                "user_id": user.id,
                "chat_id": sent.chat_id,
                "message_id": sent.message_id,
                "answer": answer,
                "expires_at": expires,
            },
            name=name,
        )
    return True


async def captcha_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data if context.job else None
    if not isinstance(data, dict):
        return
    user_id = int(data["user_id"])
    database = ctx.db(context)
    answer = str(data.get("answer", ""))
    expires_at = int(data.get("expires_at", 0))
    if not answer or not await database.delete_captcha_if_matches(
        user_id, answer, expires_at
    ):
        return
    try:
        user = await database.get_user(user_id)
        lang = ctx.user_lang(user) if user else "zh"
        await context.bot.send_message(user_id, t("captcha.timed_out", lang))
    except TelegramError:
        pass
    try:
        await context.bot.delete_message(int(data["chat_id"]), int(data["message_id"]))
    except TelegramError:
        pass
