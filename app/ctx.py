from __future__ import annotations

from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from app.i18n import FALLBACK, resolve_lang

if TYPE_CHECKING:
    from app.admins import AdminStore
    from app.config import Config
    from app.db import Database
    from app.services.settings import SettingsService


def db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.bot_data["db"]


def settings_svc(context: ContextTypes.DEFAULT_TYPE) -> SettingsService:
    return context.bot_data["settings_svc"]


def admins(context: ContextTypes.DEFAULT_TYPE) -> AdminStore:
    return context.bot_data["admins"]


def config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.bot_data["config"]


def inbox_chat_ids(context: ContextTypes.DEFAULT_TYPE) -> list[int]:
    cfg = config(context)
    if cfg.admin_chat_id:
        return [cfg.admin_chat_id]
    return sorted(admins(context).all_ids)


def user_lang(user) -> str:
    code = getattr(user, "language_code", None) or getattr(user, "ui_lang", None)
    return resolve_lang(code, FALLBACK)


def admin_lang_user(user, context: ContextTypes.DEFAULT_TYPE) -> str:
    forced = settings_svc(context).current.ui_language
    if forced and forced != "auto":
        return resolve_lang(forced)
    return resolve_lang(getattr(user, "language_code", None), FALLBACK)


def admin_lang(update: Update | None, context: ContextTypes.DEFAULT_TYPE) -> str:
    user = update.effective_user if update is not None else None
    return admin_lang_user(user, context)


def lang_from_query(query, context: ContextTypes.DEFAULT_TYPE) -> str:
    return admin_lang_user(getattr(query, "from_user", None), context)
