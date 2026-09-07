from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app import ctx
from app.handlers.common import safe_reply
from app.i18n import t
from app.services.forwarding import copy_to_user
from app.services.topics import is_user_topic


async def on_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if get_await_action(context):
        return
    message = update.effective_message
    if not message:
        return
    lang = ctx.admin_lang(update, context)
    database = ctx.db(context)
    user_id = None

    if message.reply_to_message:
        reply = message.reply_to_message
        if not (reply.from_user and context.bot.id and reply.from_user.id != context.bot.id):
            mapped = await database.map_by_admin(message.chat_id, reply.message_id)
            if mapped:
                user_id = mapped.user_id

    if user_id is None and is_user_topic(message.message_thread_id):
        topic_user = await database.get_user_by_topic(int(message.message_thread_id))
        if topic_user:
            user_id = topic_user.user_id

    if user_id is None:
        if message.chat.type == "private":
            await safe_reply(message, t("msg.no_mapping", lang))
        return
    ok = await copy_to_user(context, user_id, message)
    if not ok:
        await safe_reply(message, t("msg.user_blocked", lang))


def get_await_action(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    data = context.user_data.get("await")
    if isinstance(data, dict):
        action = data.get("action")
        return str(action) if action else None
    return None
