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
    user = await database.get_user(user_id)
    if user and user.muted_until > ts:
        return False, user.muted_until - ts

    if not settings.rate_limit_enabled:
        return True, 0

    window = max(1, settings.rate_limit_window)
    limit = max(1, settings.rate_limit_count)
    since = ts - window
    await database.prune_rate_events(ts - max(window * 4, 3600))
    count = await database.count_rate_events(user_id, since)
    if count >= limit:
        mute = max(1, settings.rate_limit_mute)
        await database.set_flags(user_id, muted_until=ts + mute)
        return False, mute

    await database.add_rate_event(user_id, ts)
    return True, 0
