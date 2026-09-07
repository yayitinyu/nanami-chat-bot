from __future__ import annotations

import random
import secrets
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.i18n import t
from app.utils import now_ts

if TYPE_CHECKING:
    from telegram import User as TgUser

DECOYS = ("✗", "×", "•", "○", "□", "△")


def _button(label: str, token: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=f"c:x:{token}")


def build_button_challenge() -> tuple[str, InlineKeyboardMarkup]:
    winner = secrets.token_hex(4)
    options = [("✓", winner)]
    used_labels = {"✓"}
    while len(options) < 4:
        decoy = random.choice(DECOYS)
        if decoy in used_labels:
            continue
        used_labels.add(decoy)
        options.append((decoy, secrets.token_hex(4)))
    random.shuffle(options)
    markup = InlineKeyboardMarkup([[_button(label, token)] for label, token in options])
    return winner, markup


def build_math_challenge(lang: str = "zh") -> tuple[str, InlineKeyboardMarkup, str]:
    a = random.randint(2, 9)
    b = random.randint(2, 9)
    correct = a + b
    winner = secrets.token_hex(4)
    choices = {correct}
    while len(choices) < 4:
        delta = random.choice([-4, -3, -2, -1, 1, 2, 3, 4, 5])
        choices.add(max(1, correct + delta))
    ordered = list(choices)
    random.shuffle(ordered)
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
) -> None:
    database = ctx.db(context)
    settings = ctx.settings_svc(context).current
    lang = ctx.user_lang(user)
    existing = await database.get_captcha(user.id)
    if existing and existing[2] > now_ts():
        await message.reply_text(t("captcha.pending", lang))
        return
    if settings.captcha_type == "math":
        answer, markup, prompt = build_math_challenge(lang)
    else:
        answer, markup = build_button_challenge()
        prompt = t("captcha.button", lang)
    expires = now_ts() + settings.captcha_timeout
    await database.set_captcha(user.id, answer, expires)
    sent = await message.reply_text(prompt, reply_markup=markup)
    job_queue = context.job_queue
    if job_queue is not None:
        name = f"captcha:{user.id}"
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()
        job_queue.run_once(
            captcha_timeout,
            when=settings.captcha_timeout,
            data={"user_id": user.id, "chat_id": sent.chat_id, "message_id": sent.message_id},
            name=name,
        )


async def captcha_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data if context.job else None
    if not isinstance(data, dict):
        return
    user_id = int(data["user_id"])
    database = ctx.db(context)
    challenge = await database.get_captcha(user_id)
    if not challenge:
        return
    await database.delete_captcha(user_id)
    try:
        user = await database.get_user(user_id)
        lang = ctx.user_lang(user) if user else "zh"
        await context.bot.send_message(user_id, t("captcha.timeout", lang))
    except TelegramError:
        pass
    try:
        await context.bot.delete_message(int(data["chat_id"]), int(data["message_id"]))
    except TelegramError:
        pass


async def pending_captcha(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    settings = ctx.settings_svc(context).current
    if not settings.captcha_enabled:
        return False
    database = ctx.db(context)
    user = await database.get_user(user_id)
    return bool(user and not user.captcha_passed)
