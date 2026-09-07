from __future__ import annotations

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app import ctx, keyboards, texts
from app.handlers.common import edit_panel
from app.i18n import format_duration, t
from app.utils import page_count


def _lang(query, context) -> str:
    return ctx.lang_from_query(query, context)


async def show_main(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    database = ctx.db(context)
    total = await database.count_users()
    banned = await database.count_users(banned_only=True)
    active = await database.count_users(active_only=True)
    today = await database.get_stats()
    await edit_panel(
        query,
        texts.main_text(total, banned, active, today, lang),
        keyboards.main_menu(lang),
    )


async def show_users(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    banned_only: bool = False,
    search: str | None = None,
) -> None:
    lang = _lang(query, context)
    database = ctx.db(context)
    per_page = keyboards.USERS_PER_PAGE
    total = await database.count_users(banned_only=banned_only, search=search)
    pages = page_count(total, per_page)
    page = max(0, min(page, pages - 1))
    users = await database.list_users(
        offset=page * per_page,
        limit=per_page,
        banned_only=banned_only,
        search=search,
    )
    rows = []
    for user in users:
        flag = "🚫 " if user.is_banned else ""
        uname = f"@{user.username}" if user.username else str(user.user_id)
        rows.append((user.user_id, f"{flag}{user.full_name} · {uname}"))
    title = t("users.title", lang)
    if search:
        title += "\n" + t("users.search", lang, q=search)
    title += "\n" + t("users.total", lang, n=total)
    await edit_panel(
        query,
        title,
        keyboards.user_list_keyboard(rows, page, pages, banned_only, lang),
    )


async def show_user(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> None:
    lang = _lang(query, context)
    user = await ctx.db(context).get_user(user_id)
    if user is None:
        await edit_panel(query, t("msg.user_not_found", lang), keyboards.main_menu(lang))
        return
    await edit_panel(
        query,
        texts.user_card(user, lang),
        keyboards.user_card_keyboard(user_id, user.is_banned, lang),
    )


async def show_start(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    settings = ctx.settings_svc(context).current
    await edit_panel(query, texts.start_preview(settings, lang), keyboards.start_menu(lang))


async def show_spam(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    settings = ctx.settings_svc(context).current
    await edit_panel(query, texts.antispam_overview(settings, lang), keyboards.antispam_menu(settings, lang))


async def show_captcha(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    settings = ctx.settings_svc(context).current
    await edit_panel(query, texts.captcha_text(settings, lang), keyboards.captcha_menu(settings, lang))


async def show_rate(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    settings = ctx.settings_svc(context).current
    await edit_panel(query, texts.rate_text(settings, lang), keyboards.rate_menu(settings, lang))


async def show_keyword_filter(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    database = ctx.db(context)
    settings = ctx.settings_svc(context).current
    items = await database.list_filter_keywords()
    await edit_panel(
        query,
        texts.keyword_filter_text(settings, [k for _, k in items], lang),
        keyboards.keyword_filter_menu(items, lang),
    )


async def show_language(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    settings = ctx.settings_svc(context).current
    await edit_panel(query, texts.language_text(settings, lang), keyboards.language_menu(settings, lang))


async def show_media(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    settings = ctx.settings_svc(context).current
    await edit_panel(query, texts.media_text(settings, lang), keyboards.media_menu(settings, lang))


async def show_link(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    settings = ctx.settings_svc(context).current
    items = await ctx.db(context).list_allow_domains()
    await edit_panel(
        query,
        texts.link_text(settings, [d for _, d in items], lang),
        keyboards.link_menu(settings, items, lang),
    )


async def show_auto_reply(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    items = await ctx.db(context).list_auto_replies()
    silent = ctx.settings_svc(context).current.auto_reply_silent
    listing = [(i.id, i.keyword, i.match_type, i.is_enabled) for i in items]
    kb_items = [(i.id, i.keyword, i.is_enabled) for i in items]
    await edit_panel(
        query,
        texts.auto_reply_text(listing, lang),
        keyboards.auto_reply_menu_with_silent(kb_items, silent, lang),
    )


async def show_broadcast(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    items = await ctx.db(context).list_broadcasts()
    rows = []
    kb = []
    for item in items:
        summary = (item.text or item.media_type or "msg")[:40]
        interval = (
            format_duration(item.interval_seconds, lang) if item.interval_seconds else t("once", lang)
        )
        rows.append((item.id, summary, item.is_enabled, interval))
        kb.append((item.id, item.is_enabled))
    await edit_panel(query, texts.broadcast_list_text(rows, lang), keyboards.broadcast_menu(kb, lang))


async def show_admins(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    store = ctx.admins(context)
    ids = sorted(store.all_ids)
    await edit_panel(
        query,
        f"{t('admins.title', lang)}\n\n{t('admins.help', lang)}",
        keyboards.admins_menu(ids, store.env_ids, lang),
    )


async def show_ui(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _lang(query, context)
    settings = ctx.settings_svc(context).current
    await edit_panel(query, texts.ui_text(settings, lang), keyboards.ui_menu(settings, lang))
