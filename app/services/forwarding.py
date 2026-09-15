from __future__ import annotations

import logging

from telegram import Message
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from app import ctx
from app.i18n import t
from app.models import User
from app.services.topics import send_to_topic, topics_enabled
from app.utils import escape, user_header

log = logging.getLogger(__name__)


def _copied_id(result: object) -> int:
    if hasattr(result, "message_id"):
        return int(result.message_id)
    return int(result)


async def _map(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    user_chat_id: int,
    user_message_id: int,
    admin_chat_id: int,
    admin_message_id: int,
    direction: str,
) -> None:
    await ctx.db(context).add_map(
        user_id=user_id,
        user_chat_id=user_chat_id,
        user_message_id=user_message_id,
        admin_chat_id=admin_chat_id,
        admin_message_id=admin_message_id,
        direction=direction,
    )


async def relay_user_message(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    message: Message,
    *,
    note: str = "",
    lang: str = "zh",
) -> None:
    destinations = ctx.inbox_chat_ids(context)
    header = user_header(user, note)
    use_topics = await topics_enabled(context)

    for chat_id in destinations:
        try:
            if use_topics and chat_id == ctx.config(context).admin_chat_id:

                async def _send(thread_id: int | None, *, _chat=chat_id) -> int:
                    copied = await message.copy(
                        _chat,
                        message_thread_id=thread_id,
                    )
                    cid = _copied_id(copied)
                    await _map(
                        context,
                        user_id=user.user_id,
                        user_chat_id=message.chat_id,
                        user_message_id=message.message_id,
                        admin_chat_id=_chat,
                        admin_message_id=cid,
                        direction="in",
                    )
                    return cid

                await send_to_topic(context, user, lang=lang, send=_send)
                continue

            header_msg = await context.bot.send_message(
                chat_id,
                header,
                parse_mode="HTML",
            )
            copied = await message.copy(chat_id, reply_to_message_id=header_msg.message_id)
            copied_id = _copied_id(copied)
            await _map(
                context,
                user_id=user.user_id,
                user_chat_id=message.chat_id,
                user_message_id=message.message_id,
                admin_chat_id=chat_id,
                admin_message_id=header_msg.message_id,
                direction="in_header",
            )
            await _map(
                context,
                user_id=user.user_id,
                user_chat_id=message.chat_id,
                user_message_id=message.message_id,
                admin_chat_id=chat_id,
                admin_message_id=copied_id,
                direction="in",
            )
        except Forbidden:
            log.warning("cannot deliver inbox to %s", chat_id)
        except TelegramError:
            log.exception("failed to relay message to %s", chat_id)


async def relay_album(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    messages: list[Message],
    *,
    note: str = "",
    lang: str = "zh",
) -> None:
    if not messages:
        return
    destinations = ctx.inbox_chat_ids(context)
    header = user_header(user, note or t("note.album", lang, n=len(messages)))
    first = messages[0]
    use_topics = await topics_enabled(context)

    for chat_id in destinations:
        try:
            if use_topics and chat_id == ctx.config(context).admin_chat_id:

                async def _send(thread_id: int | None, *, _chat=chat_id) -> int:
                    last = 0
                    for item in messages:
                        copied = await item.copy(_chat, message_thread_id=thread_id)
                        cid = _copied_id(copied)
                        last = cid
                        await _map(
                            context,
                            user_id=user.user_id,
                            user_chat_id=item.chat_id,
                            user_message_id=item.message_id,
                            admin_chat_id=_chat,
                            admin_message_id=cid,
                            direction="in",
                        )
                    return last

                await send_to_topic(context, user, lang=lang, send=_send)
                continue

            header_msg = await context.bot.send_message(
                chat_id,
                header,
                parse_mode="HTML",
            )
            await _map(
                context,
                user_id=user.user_id,
                user_chat_id=first.chat_id,
                user_message_id=first.message_id,
                admin_chat_id=chat_id,
                admin_message_id=header_msg.message_id,
                direction="in_header",
            )
            last_id = header_msg.message_id
            for item in messages:
                copied = await item.copy(chat_id, reply_to_message_id=last_id)
                copied_id = _copied_id(copied)
                last_id = copied_id
                await _map(
                    context,
                    user_id=user.user_id,
                    user_chat_id=item.chat_id,
                    user_message_id=item.message_id,
                    admin_chat_id=chat_id,
                    admin_message_id=copied_id,
                    direction="in",
                )
        except Forbidden:
            log.warning("cannot deliver album to %s", chat_id)
        except TelegramError:
            log.exception("failed to relay album to %s", chat_id)


async def copy_to_user(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    message: Message,
) -> bool:
    database = ctx.db(context)
    try:
        copied = await message.copy(user_id)
        copied_id = _copied_id(copied)
        await database.add_map(
            user_id=user_id,
            user_chat_id=user_id,
            user_message_id=copied_id,
            admin_chat_id=message.chat_id,
            admin_message_id=message.message_id,
            direction="out",
        )
        await database.incr_stat("messages_out")
        return True
    except Forbidden:
        await database.set_flags(user_id, is_blocked=True)
        return False
    except TelegramError:
        log.exception("failed to copy message to user %s", user_id)
        return False


async def notify_admins(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    parse_mode: str | None = "HTML",
) -> None:
    for chat_id in ctx.inbox_chat_ids(context):
        try:
            kwargs = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
            await context.bot.send_message(**kwargs)
        except TelegramError:
            log.warning("admin notify failed for %s", chat_id)


async def notify_filter(
    context: ContextTypes.DEFAULT_TYPE,
    user: User,
    verdict_reason: str,
    detail: str,
    lang: str = "zh",
) -> None:
    settings = ctx.settings_svc(context).current
    if not settings.notify_admin_on_filter:
        return
    label = t(f"admin_reason.{verdict_reason}", lang)
    extra = f" · {escape(detail[:300])}" if detail else ""
    await notify_admins(
        context,
        t("intercept", lang, label=label, extra=extra, header=user_header(user)),
    )
