from __future__ import annotations

from telegram.ext import ContextTypes

from app import ctx
from app.utils import now_ts


async def check_and_hit(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> tuple[bool, int]:
    """
    Record a message and return (allowed, remaining_mute_seconds).
    remaining_mute_seconds is 0 when allowed.
    """
    settings = ctx.settings_svc(context).current
    database = ctx.db(context)
    ts = now_ts()
    window = max(1, settings.rate_limit_window)
    return await database.admit_rate_event(
        user_id,
        ts=ts,
        enabled=settings.rate_limit_enabled,
        window=window,
        limit=max(1, settings.rate_limit_count),
        mute=max(1, settings.rate_limit_mute),
        prune_before=ts - max(window * 4, 3600),
    )
