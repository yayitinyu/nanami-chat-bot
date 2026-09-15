from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import Application, ContextTypes

from app import ctx
from app.db import Database
from app.i18n import t
from app.models import Broadcast
from app.utils import extract_media, now_ts

log = logging.getLogger(__name__)

JOB_PREFIX = "broadcast:"


def job_name(broadcast_id: int) -> str:
    return f"{JOB_PREFIX}{broadcast_id}"


def retry_after_seconds(value: int | timedelta) -> float:
    if isinstance(value, timedelta):
        return max(0.0, value.total_seconds())
    return max(0.0, float(value))


async def send_one(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    item: Broadcast,
) -> bool:
    bot = context.bot
    try:
        if item.from_chat_id and item.from_message_id:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=item.from_chat_id,
                message_id=item.from_message_id,
            )
            return True
        if item.media_type and item.media_file_id:
            method = {
                "photo": bot.send_photo,
                "video": bot.send_video,
                "animation": bot.send_animation,
                "document": bot.send_document,
                "audio": bot.send_audio,
                "sticker": bot.send_sticker,
                "voice": bot.send_voice,
                "video_note": bot.send_video_note,
            }.get(item.media_type)
            if method is None:
                return False
            kwargs = {"chat_id": user_id}
            if item.media_type == "photo":
                kwargs["photo"] = item.media_file_id
                if item.text:
                    kwargs["caption"] = item.text
            elif item.media_type == "sticker":
                kwargs["sticker"] = item.media_file_id
            elif item.media_type == "voice":
                kwargs["voice"] = item.media_file_id
            elif item.media_type == "video_note":
                kwargs["video_note"] = item.media_file_id
            else:
                kwargs[item.media_type] = item.media_file_id
                if item.text:
                    kwargs["caption"] = item.text
            await method(**kwargs)
            return True
        if item.text:
            await bot.send_message(user_id, item.text)
            return True
        return False
    except Forbidden:
        await ctx.db(context).set_flags(user_id, is_blocked=True)
        return False
    except RetryAfter as exc:
        log.warning("broadcast retry_after %s", exc.retry_after)
        raise
    except TelegramError:
        log.exception("broadcast failed for %s", user_id)
        return False


async def deliver(
    context: ContextTypes.DEFAULT_TYPE,
    item: Broadcast,
    *,
    notify_chat_id: int | None = None,
    lang: str = "zh",
) -> tuple[int, int]:
    database = ctx.db(context)
    targets = await database.broadcast_targets()
    ok = 0
    fail = 0
    if notify_chat_id:
        try:
            await context.bot.send_message(
                notify_chat_id,
                t("bc.started", lang, n=len(targets)),
            )
        except TelegramError:
            pass
    for user_id in targets:
        try:
            if await send_one(context, user_id, item):
                ok += 1
            else:
                fail += 1
        except RetryAfter as exc:
            await _sleep(retry_after_seconds(exc.retry_after) + 0.5)
            try:
                if await send_one(context, user_id, item):
                    ok += 1
                else:
                    fail += 1
            except TelegramError:
                fail += 1
    await database.incr_stat("broadcast_sent", ok)
    next_send = None
    if item.interval_seconds:
        next_send = now_ts() + item.interval_seconds
    await database.mark_broadcast_sent(item.id, next_send)
    if notify_chat_id:
        try:
            await context.bot.send_message(
                notify_chat_id,
                t("bc.done", lang, ok=ok, fail=fail),
            )
        except TelegramError:
            pass
    return ok, fail


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


async def job_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data if context.job else None
    if not isinstance(data, dict):
        return
    broadcast_id = int(data["broadcast_id"])
    item = await ctx.db(context).get_broadcast(broadcast_id)
    if item is None or not item.is_enabled:
        return
    await deliver(context, item)


def schedule(application: Application, item: Broadcast) -> None:
    job_queue = application.job_queue
    if job_queue is None or not item.interval_seconds or not item.is_enabled:
        return
    name = job_name(item.id)
    for job in job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    first: float | datetime
    if item.next_send_at and item.next_send_at > now_ts():
        first = datetime.fromtimestamp(item.next_send_at, timezone.utc)
    else:
        first = 5
    job_queue.run_repeating(
        job_callback,
        interval=item.interval_seconds,
        first=first,
        data={"broadcast_id": item.id},
        name=name,
    )


def unschedule(application: Application, broadcast_id: int) -> None:
    job_queue = application.job_queue
    if job_queue is None:
        return
    for job in job_queue.get_jobs_by_name(job_name(broadcast_id)):
        job.schedule_removal()


async def restore_jobs(application: Application) -> None:
    database: Database = application.bot_data["db"]
    items = await database.list_enabled_repeating_broadcasts()
    for item in items:
        schedule(application, item)
    log.info("restored %s repeating broadcasts", len(items))


def draft_from_message(message) -> dict:
    media_type, file_id, text = extract_media(message)
    return {
        "text": text,
        "media_file_id": file_id,
        "media_type": media_type,
        "from_chat_id": message.chat_id,
        "from_message_id": message.message_id,
    }
