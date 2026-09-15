from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.handlers.common import admit_global_update


async def _global_rate_flow() -> None:
    context = SimpleNamespace(
        bot_data={
            "config": SimpleNamespace(
                global_rate_limit_count=3,
                global_rate_limit_window=60,
            )
        }
    )
    assert await admit_global_update(context, consume=False)
    assert len(context.bot_data["global_rate_events"]) == 0
    results = await asyncio.gather(
        *[admit_global_update(context) for _ in range(20)]
    )
    assert sum(results) == 3
    assert len(context.bot_data["global_rate_events"]) == 3


def test_global_rate_budget_is_atomic_and_bounded() -> None:
    asyncio.run(_global_rate_flow())
