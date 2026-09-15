from __future__ import annotations

import asyncio

import pytest

from app.admins import AdminStore
from app.models import BotSettings, next_captcha_type
from app.services.settings import SettingsService


class FailingSettingsDb:
    async def save_bot_settings(self, settings: BotSettings) -> None:
        raise RuntimeError("write failed")


class FailingAdminDb:
    async def set_extra_admin_ids(self, ids: list[int]) -> None:
        raise RuntimeError("write failed")


class YieldingSettingsDb:
    async def save_bot_settings(self, settings: BotSettings) -> None:
        await asyncio.sleep(0)


async def _settings_failure() -> None:
    service = SettingsService(FailingSettingsDb())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="write failed"):
        await service.update(captcha_enabled=True)
    assert service.current.captcha_enabled is False


async def _admin_failure() -> None:
    store = AdminStore([1])
    with pytest.raises(RuntimeError, match="write failed"):
        await store.add(FailingAdminDb(), 2)  # type: ignore[arg-type]
    assert store.all_ids == {1}


def test_failed_settings_save_does_not_mutate_live_state() -> None:
    asyncio.run(_settings_failure())


def test_failed_admin_save_does_not_mutate_live_state() -> None:
    asyncio.run(_admin_failure())


async def _concurrent_toggle() -> None:
    service = SettingsService(YieldingSettingsDb())  # type: ignore[arg-type]
    results = await asyncio.gather(
        service.toggle("captcha_enabled"),
        service.toggle("captcha_enabled"),
    )
    assert results == [True, False]
    assert service.current.captcha_enabled is False


def test_concurrent_toggles_are_serialized() -> None:
    asyncio.run(_concurrent_toggle())


async def _concurrent_mutation() -> None:
    service = SettingsService(YieldingSettingsDb())  # type: ignore[arg-type]

    def toggle_type(settings: BotSettings) -> None:
        settings.captcha_type = next_captcha_type(settings.captcha_type)

    await asyncio.gather(
        service.mutate(toggle_type),
        service.mutate(toggle_type),
        service.mutate(toggle_type),
    )
    assert service.current.captcha_type == "button"


def test_concurrent_composite_mutations_are_serialized() -> None:
    asyncio.run(_concurrent_mutation())
