from __future__ import annotations

import asyncio
import logging
import os
import sys
from urllib.parse import urlparse

from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    ContextTypes,
)

from app.admins import AdminStore
from app.config import Config
from app.db import Database
from app.handlers import register
from app.services.broadcast import restore_jobs
from app.services.settings import SettingsService
from app.utils import now_ts, set_timezone

log = logging.getLogger(__name__)
ALLOWED_UPDATES = ["message", "edited_message", "callback_query", "my_chat_member"]
MAP_PRUNE_JOB = "maintenance:message-map-prune"


def setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


async def post_init(application: Application) -> None:
    database: Database = application.bot_data["db"]
    await database.init()
    settings_svc: SettingsService = application.bot_data["settings_svc"]
    await settings_svc.load()
    store: AdminStore = application.bot_data["admins"]
    await store.load(database)
    await prune_message_maps(application)
    if application.job_queue is not None:
        application.job_queue.run_repeating(
            prune_message_maps_job,
            interval=3600,
            first=3600,
            name=MAP_PRUNE_JOB,
        )
    await restore_jobs(application)
    me = await application.bot.get_me()
    log.info("bot @%s ready, admins=%s", me.username, sorted(store.all_ids))


async def prune_message_maps(application: Application) -> int:
    database: Database = application.bot_data["db"]
    config: Config = application.bot_data["config"]
    removed = await database.prune_message_maps(
        now_ts() - config.message_map_retention_days * 86400
    )
    expired_captchas = await database.prune_expired_captchas(now_ts())
    if removed:
        log.info("pruned %s expired message mappings", removed)
    if expired_captchas:
        log.info("pruned %s expired captcha challenges", expired_captchas)
    return removed


async def prune_message_maps_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await prune_message_maps(context.application)


async def post_shutdown(application: Application) -> None:
    database: Database = application.bot_data.get("db")
    if database is not None:
        await database.close()


def build_application(config: Config) -> Application:
    store = AdminStore(config.admin_ids)
    database = Database(config.database_path)
    settings_svc = SettingsService(database)

    application = (
        ApplicationBuilder()
        .token(config.bot_token)
        .update_queue(asyncio.Queue(maxsize=config.update_queue_size))
        .rate_limiter(AIORateLimiter(max_retries=3))
        .concurrent_updates(config.max_concurrent_updates)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["config"] = config
    application.bot_data["db"] = database
    application.bot_data["settings_svc"] = settings_svc
    application.bot_data["admins"] = store
    if application.job_queue is not None:
        from zoneinfo import ZoneInfo

        application.job_queue.scheduler.configure(timezone=ZoneInfo(config.tz))
    register(application, store)
    return application


def main() -> None:
    if os.name == "posix":
        os.umask(0o077)
    config = Config()
    if not config.admin_ids:
        raise SystemExit("ADMIN_IDS is required")
    set_timezone(config.tz)
    setup_logging(config.log_level)
    log.info(
        "database=%s tz=%s concurrent=%s queue=%s global_budget=%s/%ss",
        config.database_path,
        config.tz,
        config.max_concurrent_updates,
        config.update_queue_size,
        config.global_rate_limit_count,
        config.global_rate_limit_window,
    )
    application = build_application(config)
    if config.webhook_enabled:
        path = config.webhook_url_path
        public_host = urlparse(config.webhook_url or "").hostname or "-"
        log.info(
            "webhook listen=%s:%s public_host=%s",
            config.webhook_listen,
            config.webhook_port,
            public_host,
        )
        application.run_webhook(
            listen=config.webhook_listen,
            port=config.webhook_port,
            url_path=path,
            webhook_url=config.webhook_public_url,
            secret_token=config.webhook_secret,
            max_connections=config.webhook_max_connections,
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=False,
        )
        return
    log.info("polling mode")
    application.run_polling(allowed_updates=ALLOWED_UPDATES, drop_pending_updates=False)
