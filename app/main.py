from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.ext import AIORateLimiter, Application, ApplicationBuilder

from app.admins import AdminStore
from app.config import Config
from app.db import Database
from app.handlers import register
from app.services.broadcast import restore_jobs
from app.services.settings import SettingsService
from app.utils import set_timezone

log = logging.getLogger(__name__)


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
    await restore_jobs(application)
    me = await application.bot.get_me()
    log.info("bot @%s ready, admins=%s", me.username, sorted(store.all_ids))


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
        .rate_limiter(AIORateLimiter(max_retries=3))
        .concurrent_updates(True)
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
    config = Config()
    if not config.admin_ids:
        raise SystemExit("ADMIN_IDS is required")
    set_timezone(config.tz)
    setup_logging(config.log_level)
    log.info("database=%s tz=%s", config.database_path, config.tz)
    application = build_application(config)
    if config.webhook_enabled:
        path = config.webhook_url_path
        log.info("webhook listen=%s:%s path=/%s url=%s", config.webhook_listen, config.webhook_port, path, config.webhook_url)
        application.run_webhook(
            listen=config.webhook_listen,
            port=config.webhook_port,
            url_path=path,
            webhook_url=config.webhook_url,
            secret_token=config.webhook_secret,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )
        return
    log.info("polling mode")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
