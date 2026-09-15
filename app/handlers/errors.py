from __future__ import annotations

import logging

from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import ContextTypes

from app.services.forwarding import notify_admins

log = logging.getLogger(__name__)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, (TimedOut, NetworkError)):
        log.warning("transient telegram error: %s", err)
        return
    log.exception("unhandled error: %s", err)
    if isinstance(update, Update) and ctx_has_db(context):
        try:
            await notify_admins(context, f"内部错误：{type(err).__name__}")
        except Exception:
            log.exception("failed to notify admins about an unhandled error")


def ctx_has_db(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return "db" in context.bot_data
