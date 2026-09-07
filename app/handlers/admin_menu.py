from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app import ctx, keyboards, texts
from app.handlers import admin_await, panels
from app.handlers.admin_reply import on_admin_reply
from app.handlers.common import clear_await, safe_reply, set_await
from app.i18n import t
from app.models import MEDIA_TYPES
from app.services.broadcast import deliver, schedule, unschedule
from app.services.topics import is_user_topic


log = logging.getLogger(__name__)


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_await(context)
    message = update.effective_message
    if not message:
        return
    database = ctx.db(context)
    total = await database.count_users()
    banned = await database.count_users(banned_only=True)
    active = await database.count_users(active_only=True)
    today = await database.get_stats()
    lang = ctx.admin_lang(update, context)
    await message.reply_text(
        texts.main_text(total, banned, active, today, lang),
        parse_mode="HTML",
        reply_markup=keyboards.main_menu(lang),
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_await(context)
    context.user_data.pop("bc_draft", None)
    message = update.effective_message
    if message:
        await safe_reply(message, t("msg.cancelled", ctx.admin_lang(update, context)))


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ban_cmd(update, context, banned=True)


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ban_cmd(update, context, banned=False)


async def _ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, banned: bool) -> None:
    message = update.effective_message
    if not message:
        return
    database = ctx.db(context)
    user_id = None
    if context.args:
        found = await database.find_user(" ".join(context.args))
        user_id = found.user_id if found else None
        if user_id is None and context.args[0].lstrip("-").isdigit():
            user_id = int(context.args[0])
    elif message.reply_to_message:
        mapped = await database.map_by_admin(message.chat_id, message.reply_to_message.message_id)
        if mapped:
            user_id = mapped.user_id
    if user_id is None and message.message_thread_id and is_user_topic(message.message_thread_id):
        topic_user = await database.get_user_by_topic(int(message.message_thread_id))
        if topic_user:
            user_id = topic_user.user_id
    lang = ctx.admin_lang(update, context)
    if user_id is None:
        await safe_reply(message, t("msg.ban_usage", lang))
        return
    await database.set_flags(user_id, is_banned=banned)
    await database.incr_stat("banned" if banned else "unbanned")
    await safe_reply(message, t("msg.banned_ok" if banned else "msg.unbanned_ok", lang))
    if banned:
        try:
            target = await database.get_user(user_id)
            await context.bot.send_message(
                user_id,
                t("filter.banned", ctx.user_lang(target) if target else "zh"),
            )
        except TelegramError:
            pass


async def on_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message and message.chat.type != "private":
        inbox = ctx.config(context).admin_chat_id
        if inbox is None or message.chat.id != inbox:
            return
    if await admin_await.handle(update, context):
        return
    if message and (message.reply_to_message or is_user_topic(message.message_thread_id)):
        await on_admin_reply(update, context)
        return
    if message and message.chat.type == "private":
        await safe_reply(message, t("msg.reply_hint", ctx.admin_lang(update, context)))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.data or not user:
        return
    data = query.data
    if data == "noop":
        await query.answer()
        return
    if not ctx.admins(context).is_admin(user.id):
        await query.answer(t("msg.not_admin", ctx.admin_lang(update, context)), show_alert=True)
        return

    if data == "m:close":
        await query.answer()
        try:
            await query.message.delete()
        except TelegramError:
            pass
        return

    await query.answer()

    if data in {"m:main", "m:users", "m:bc", "m:ar", "m:start", "m:spam", "m:admins", "m:ui"}:
        await _show(data, query, context)
        return

    prefix, _, rest = data.partition(":")
    router = {
        "u": _users,
        "st": _start_msg,
        "sp": _spam,
        "cap": _captcha,
        "rt": _rate,
        "kf": _keyword_filter,
        "lg": _language,
        "md": _media,
        "ln": _link,
        "ar": _auto_reply,
        "bc": _broadcast,
        "ad": _admins,
        "ui": _ui,
    }.get(prefix)
    if router:
        await router(query, context, rest)


async def _show(data: str, query, context) -> None:
    mapping = {
        "m:main": panels.show_main,
        "m:users": panels.show_users,
        "m:bc": panels.show_broadcast,
        "m:ar": panels.show_auto_reply,
        "m:start": panels.show_start,
        "m:spam": panels.show_spam,
        "m:admins": panels.show_admins,
        "m:ui": panels.show_ui,
    }
    await mapping[data](query, context)


async def _users(query, context, rest: str) -> None:
    parts = rest.split(":")
    cmd = parts[0]
    if cmd == "p":
        page = int(parts[1]) if len(parts) > 1 else 0
        banned_only = bool(int(parts[2])) if len(parts) > 2 else False
        await panels.show_users(query, context, page=page, banned_only=banned_only)
        return
    if cmd == "search":
        set_await(context, "search")
        if query.message:
            await query.message.reply_text(t("prompt.search", ctx.lang_from_query(query, context)))
        return
    if cmd == "id" and len(parts) > 1:
        await panels.show_user(query, context, int(parts[1]))
        return
    if cmd in {"ban", "unban"} and len(parts) > 1:
        user_id = int(parts[1])
        await ctx.db(context).set_flags(user_id, is_banned=cmd == "ban")
        if cmd == "ban":
            try:
                target = await ctx.db(context).get_user(user_id)
                await context.bot.send_message(
                    user_id,
                    t("filter.banned", ctx.user_lang(target) if target else "zh"),
                )
            except TelegramError:
                pass
        await panels.show_user(query, context, user_id)
        return
    if cmd == "msg" and len(parts) > 1:
        set_await(context, "user_msg", user_id=int(parts[1]))
        if query.message:
            await query.message.reply_text(t("prompt.user_msg", ctx.lang_from_query(query, context)))
        return
    if cmd == "cap" and len(parts) > 1:
        await ctx.db(context).set_flags(int(parts[1]), captcha_passed=False)
        await ctx.db(context).delete_captcha(int(parts[1]))
        await panels.show_user(query, context, int(parts[1]))


async def _start_msg(query, context, rest: str) -> None:
    if rest == "edit":
        set_await(context, "start")
        if query.message:
            await query.message.reply_text(t("prompt.start", ctx.lang_from_query(query, context)))
        return
    if rest == "preview":
        text = ctx.settings_svc(context).current.start_message
        if query.message:
            try:
                await query.message.reply_text(text, parse_mode="HTML")
            except TelegramError:
                await query.message.reply_text(text)
        return
    await panels.show_start(query, context)


async def _spam(query, context, rest: str) -> None:
    if rest == "cap":
        await panels.show_captcha(query, context)
        return
    if rest == "rate":
        await panels.show_rate(query, context)
        return
    if rest == "kw":
        await panels.show_keyword_filter(query, context)
        return
    if rest == "lang":
        await panels.show_language(query, context)
        return
    if rest == "media":
        await panels.show_media(query, context)
        return
    if rest == "link":
        await panels.show_link(query, context)
        return
    if rest == "nadmin":
        await ctx.settings_svc(context).toggle("notify_admin_on_filter")
    elif rest == "nuser":
        await ctx.settings_svc(context).toggle("notify_user_on_filter")
    await panels.show_spam(query, context)


async def _captcha(query, context, rest: str) -> None:
    svc = ctx.settings_svc(context)
    if rest == "toggle":
        await svc.toggle("captcha_enabled")
    elif rest == "type":
        current = svc.current.captcha_type
        await svc.update(captcha_type="math" if current == "button" else "button")
    elif rest == "ban":
        await svc.toggle("captcha_ban_on_fail")
    await panels.show_captcha(query, context)


async def _rate(query, context, rest: str) -> None:
    if rest == "toggle":
        await ctx.settings_svc(context).toggle("rate_limit_enabled")
        await panels.show_rate(query, context)
        return
    field = {
        "count": "rate_limit_count",
        "window": "rate_limit_window",
        "mute": "rate_limit_mute",
    }.get(rest)
    if field:
        set_await(context, "rate_value", field=field)
        lang = ctx.lang_from_query(query, context)
        hint = {
            "rate_limit_count": t("prompt.rate_count", lang),
            "rate_limit_window": t("prompt.rate_window", lang),
            "rate_limit_mute": t("prompt.rate_mute", lang),
        }[field]
        if query.message:
            await query.message.reply_text(hint)
        return
    await panels.show_rate(query, context)


async def _keyword_filter(query, context, rest: str) -> None:
    if rest == "toggle":
        await ctx.settings_svc(context).toggle("keyword_filter_enabled")
    elif rest == "add":
        set_await(context, "filter_kw")
        if query.message:
            await query.message.reply_text(t("prompt.filter_kw", ctx.lang_from_query(query, context)))
        return
    elif rest.startswith("del:"):
        await ctx.db(context).delete_filter_keyword(int(rest.split(":")[1]))
    await panels.show_keyword_filter(query, context)


async def _language(query, context, rest: str) -> None:
    svc = ctx.settings_svc(context)
    if rest == "toggle":
        await svc.toggle("language_filter_enabled")
    else:
        code = rest
        langs = list(svc.current.allowed_languages)
        if code in langs:
            langs = [c for c in langs if c != code]
        else:
            langs.append(code)
        await svc.update(allowed_languages=langs)
    await panels.show_language(query, context)


async def _media(query, context, rest: str) -> None:
    svc = ctx.settings_svc(context)
    if rest == "toggle":
        await svc.toggle("media_filter_enabled")
    elif rest in MEDIA_TYPES:
        blocked = list(svc.current.blocked_media)
        if rest in blocked:
            blocked = [x for x in blocked if x != rest]
        else:
            blocked.append(rest)
        await svc.update(blocked_media=blocked)
    await panels.show_media(query, context)


async def _link(query, context, rest: str) -> None:
    svc = ctx.settings_svc(context)
    if rest == "toggle":
        await svc.toggle("link_filter_enabled")
    elif rest == "mention":
        await svc.toggle("link_block_mentions")
    elif rest == "tme":
        await svc.toggle("link_block_tme")
    elif rest == "add":
        set_await(context, "domain")
        if query.message:
            await query.message.reply_text(t("prompt.domain", ctx.lang_from_query(query, context)))
        return
    elif rest.startswith("del:"):
        await ctx.db(context).delete_allow_domain(int(rest.split(":")[1]))
    await panels.show_link(query, context)


async def _auto_reply(query, context, rest: str) -> None:
    database = ctx.db(context)
    if rest == "add":
        set_await(context, "ar_keyword")
        if query.message:
            await query.message.reply_text(t("prompt.ar_keyword", ctx.lang_from_query(query, context)))
        return
    if rest == "silent":
        await ctx.settings_svc(context).toggle("auto_reply_silent")
    elif rest.startswith("tg:"):
        await database.toggle_auto_reply(int(rest.split(":")[1]))
    elif rest.startswith("del:"):
        await database.delete_auto_reply(int(rest.split(":")[1]))
    await panels.show_auto_reply(query, context)


async def _broadcast(query, context, rest: str) -> None:
    database = ctx.db(context)
    if rest == "now" or rest == "new":
        set_await(context, "broadcast")
        if query.message:
            await query.message.reply_text(t("prompt.broadcast", ctx.lang_from_query(query, context)))
        return
    if rest == "custom":
        set_await(context, "bc_interval")
        if query.message:
            await query.message.reply_text(t("prompt.bc_interval", ctx.lang_from_query(query, context)))
        return
    if rest.startswith("go:"):
        token = rest.split(":", 1)[1]
        interval = None if token == "now" else int(token)
        message = query.message
        if message is None:
            return
        # reuse commit via a synthetic path
        from app.handlers.admin_await import _commit_broadcast

        clear_await(context)
        await _commit_broadcast(
            message,
            context,
            interval,
            created_by=query.from_user.id if query.from_user else None,
        )
        await panels.show_broadcast(query, context)
        return
    if rest.startswith("tg:"):
        item_id = int(rest.split(":")[1])
        item = await database.get_broadcast(item_id)
        if item:
            enabled = not item.is_enabled
            await database.set_broadcast_enabled(item_id, enabled)
            if enabled:
                item = await database.get_broadcast(item_id)
                if item:
                    schedule(context.application, item)
            else:
                unschedule(context.application, item_id)
    elif rest.startswith("run:"):
        item_id = int(rest.split(":")[1])
        item = await database.get_broadcast(item_id)
        if item and query.message:
            await deliver(
                context,
                item,
                notify_chat_id=query.message.chat_id,
                lang=ctx.lang_from_query(query, context),
            )
    elif rest.startswith("del:"):
        item_id = int(rest.split(":")[1])
        unschedule(context.application, item_id)
        await database.delete_broadcast(item_id)
    await panels.show_broadcast(query, context)


async def _admins(query, context, rest: str) -> None:
    store = ctx.admins(context)
    if rest == "add":
        if not store.is_super_admin(query.from_user.id if query.from_user else None):
            if query.message:
                await query.message.reply_text(t("msg.not_admin", ctx.lang_from_query(query, context)))
            return
        set_await(context, "add_admin")
        if query.message:
            await query.message.reply_text(t("prompt.add_admin", ctx.lang_from_query(query, context)))
        return
    if rest.startswith("del:"):
        uid = int(rest.split(":")[1])
        if not store.is_super_admin(query.from_user.id if query.from_user else None):
            if query.message:
                await query.message.reply_text(t("msg.not_admin", ctx.lang_from_query(query, context)))
            return
        await store.remove(ctx.db(context), uid)
    await panels.show_admins(query, context)


async def _ui(query, context, rest: str) -> None:
    svc = ctx.settings_svc(context)
    if rest.startswith("lang:"):
        code = rest.split(":", 1)[1]
        await svc.update(ui_language=code)
    elif rest == "forum":
        await svc.toggle("forum_topics_enabled")
        context.bot_data.pop("inbox_is_forum", None)
    await panels.show_ui(query, context)
