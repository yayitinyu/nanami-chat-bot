from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.i18n import media_label, t
from app.models import LANG_LABELS, MEDIA_TYPES, BotSettings
from app.texts import mark, on_off

USERS_PER_PAGE = 8


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def _grid(buttons: list[InlineKeyboardButton], cols: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i : i + cols] for i in range(0, len(buttons), cols)]


def main_menu(lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_btn(t("btn.users", lang), "m:users"), _btn(t("btn.broadcast", lang), "m:bc")],
            [_btn(t("btn.auto_reply", lang), "m:ar"), _btn(t("btn.start", lang), "m:start")],
            [_btn(t("btn.antispam", lang), "m:spam"), _btn(t("btn.admins", lang), "m:admins")],
            [_btn(t("btn.ui", lang), "m:ui"), _btn(t("btn.close", lang), "m:close")],
        ]
    )


def users_menu(page: int, total_pages: int, banned_only: bool, lang: str = "zh") -> InlineKeyboardMarkup:
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(_btn("‹", f"u:p:{page - 1}:{int(banned_only)}"))
    nav.append(_btn(f"{page + 1}/{total_pages}", "noop"))
    if page + 1 < total_pages:
        nav.append(_btn("›", f"u:p:{page + 1}:{int(banned_only)}"))
    toggle = t("btn.all_users", lang) if banned_only else t("btn.banned_only", lang)
    return InlineKeyboardMarkup(
        [
            nav,
            [_btn(t("btn.search", lang), "u:search"), _btn(toggle, f"u:p:0:{int(not banned_only)}")],
            [_btn(t("btn.back", lang), "m:main")],
        ]
    )


def user_list_keyboard(
    users: list[tuple[int, str]],
    page: int,
    total_pages: int,
    banned_only: bool,
    lang: str = "zh",
) -> InlineKeyboardMarkup:
    rows = [[_btn(label, f"u:id:{uid}")] for uid, label in users]
    rows.extend(users_menu(page, total_pages, banned_only, lang).inline_keyboard)
    return InlineKeyboardMarkup(rows)


def user_card_keyboard(user_id: int, is_banned: bool, lang: str = "zh") -> InlineKeyboardMarkup:
    ban = (
        _btn(t("btn.unban", lang), f"u:unban:{user_id}")
        if is_banned
        else _btn(t("btn.ban", lang), f"u:ban:{user_id}")
    )
    return InlineKeyboardMarkup(
        [
            [ban, _btn(t("btn.send", lang), f"u:msg:{user_id}")],
            [_btn(t("btn.reset_captcha", lang), f"u:cap:{user_id}")],
            [_btn(t("btn.user_list", lang), "m:users")],
        ]
    )


def start_menu(lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_btn(t("btn.edit", lang), "st:edit"), _btn(t("btn.preview", lang), "st:preview")],
            [_btn(t("btn.back", lang), "m:main")],
        ]
    )


def antispam_menu(s: BotSettings, lang: str = "zh") -> InlineKeyboardMarkup:
    oo = lambda v: on_off(v, lang)
    return InlineKeyboardMarkup(
        [
            [_btn(t("spam.captcha", lang, v=oo(s.captcha_enabled)), "sp:cap")],
            [_btn(t("spam.rate", lang, v=oo(s.rate_limit_enabled)), "sp:rate")],
            [_btn(t("spam.keyword", lang, v=oo(s.keyword_filter_enabled)), "sp:kw")],
            [_btn(t("spam.language", lang, v=oo(s.language_filter_enabled)), "sp:lang")],
            [_btn(t("spam.media", lang, v=oo(s.media_filter_enabled)), "sp:media")],
            [_btn(t("spam.link", lang, v=oo(s.link_filter_enabled)), "sp:link")],
            [_btn(t("spam.notify_admin", lang, v=oo(s.notify_admin_on_filter)), "sp:nadmin")],
            [_btn(t("spam.notify_user", lang, v=oo(s.notify_user_on_filter)), "sp:nuser")],
            [_btn(t("btn.back", lang), "m:main")],
        ]
    )


def captcha_menu(s: BotSettings, lang: str = "zh") -> InlineKeyboardMarkup:
    kind = t("captcha.type.button" if s.captcha_type == "button" else "captcha.type.math", lang)
    return InlineKeyboardMarkup(
        [
            [_btn(f"{t('btn.toggle', lang)} {on_off(s.captcha_enabled, lang)}", "cap:toggle")],
            [_btn(t("captcha.type", lang, v=kind), "cap:type")],
            [_btn(t("captcha.ban_fail", lang, v=on_off(s.captcha_ban_on_fail, lang)), "cap:ban")],
            [_btn(t("btn.back", lang), "m:spam")],
        ]
    )


def rate_menu(s: BotSettings, lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_btn(f"{t('btn.toggle', lang)} {on_off(s.rate_limit_enabled, lang)}", "rt:toggle")],
            [
                _btn(t("btn.count", lang), "rt:count"),
                _btn(t("btn.window", lang), "rt:window"),
                _btn(t("btn.mute", lang), "rt:mute"),
            ],
            [_btn(t("btn.back", lang), "m:spam")],
        ]
    )


def keyword_filter_menu(items: list[tuple[int, str]], lang: str = "zh") -> InlineKeyboardMarkup:
    rows = [[_btn(f"× {kw}", f"kf:del:{item_id}")] for item_id, kw in items[:20]]
    rows.append([_btn(t("btn.add", lang), "kf:add")])
    rows.append([_btn(t("btn.toggle", lang), "kf:toggle"), _btn(t("btn.back", lang), "m:spam")])
    return InlineKeyboardMarkup(rows)


def language_menu(s: BotSettings, lang: str = "zh") -> InlineKeyboardMarkup:
    buttons = [
        _btn(f"{mark(code in s.allowed_languages)} {label}", f"lg:{code}")
        for code, label in LANG_LABELS.items()
    ]
    rows = _grid(buttons, 3)
    rows.insert(0, [_btn(f"{t('btn.toggle', lang)} {on_off(s.language_filter_enabled, lang)}", "lg:toggle")])
    rows.append([_btn(t("btn.back", lang), "m:spam")])
    return InlineKeyboardMarkup(rows)


def media_menu(s: BotSettings, lang: str = "zh") -> InlineKeyboardMarkup:
    buttons = [
        _btn(
            f"{mark(kind in s.blocked_media)} {media_label(kind, lang)}",
            f"md:{kind}",
        )
        for kind in MEDIA_TYPES
    ]
    rows = _grid(buttons, 2)
    rows.insert(0, [_btn(f"{t('btn.toggle', lang)} {on_off(s.media_filter_enabled, lang)}", "md:toggle")])
    rows.append([_btn(t("btn.back", lang), "m:spam")])
    return InlineKeyboardMarkup(rows)


def link_menu(s: BotSettings, domains: list[tuple[int, str]], lang: str = "zh") -> InlineKeyboardMarkup:
    rows = [[_btn(f"× {domain}", f"ln:del:{item_id}")] for item_id, domain in domains[:15]]
    rows = [
        [_btn(f"{t('btn.toggle', lang)} {on_off(s.link_filter_enabled, lang)}", "ln:toggle")],
        [_btn(f"@ {on_off(s.link_block_mentions, lang)}", "ln:mention")],
        [_btn(f"t.me {on_off(s.link_block_tme, lang)}", "ln:tme")],
        [_btn(t("btn.add_domain", lang), "ln:add")],
        *rows,
        [_btn(t("btn.back", lang), "m:spam")],
    ]
    return InlineKeyboardMarkup(rows)


def auto_reply_menu_with_silent(
    items: list[tuple[int, str, bool]], silent: bool, lang: str = "zh"
) -> InlineKeyboardMarkup:
    rows = []
    for item_id, keyword, enabled in items[:20]:
        flag = on_off(enabled, lang)
        label = keyword if len(keyword) <= 24 else keyword[:23] + "…"
        rows.append(
            [
                _btn(f"{flag} {label}", f"ar:tg:{item_id}"),
                _btn("×", f"ar:del:{item_id}"),
            ]
        )
    rows.append([_btn(t("btn.add", lang), "ar:add")])
    rows.append([_btn(t("ar.forward", lang, v=on_off(not silent, lang)), "ar:silent")])
    rows.append([_btn(t("btn.back", lang), "m:main")])
    return InlineKeyboardMarkup(rows)


def broadcast_menu(items: list[tuple[int, bool]], lang: str = "zh") -> InlineKeyboardMarkup:
    rows = [[_btn(t("btn.send_now", lang), "bc:now")]]
    rows.append([_btn(t("btn.new_timed", lang), "bc:new")])
    for item_id, enabled in items[:12]:
        flag = on_off(enabled, lang)
        rows.append(
            [
                _btn(f"{flag} #{item_id}", f"bc:tg:{item_id}"),
                _btn(t("btn.run_once", lang), f"bc:run:{item_id}"),
                _btn("×", f"bc:del:{item_id}"),
            ]
        )
    rows.append([_btn(t("btn.back", lang), "m:main")])
    return InlineKeyboardMarkup(rows)


def broadcast_when(lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_btn(t("btn.send_now", lang), "bc:go:now")],
            [
                _btn(t("btn.hourly", lang), "bc:go:3600"),
                _btn(t("btn.every_6h", lang), "bc:go:21600"),
            ],
            [
                _btn(t("btn.daily", lang), "bc:go:86400"),
                _btn(t("btn.weekly", lang), "bc:go:604800"),
            ],
            [_btn(t("btn.custom_interval", lang), "bc:custom")],
            [_btn(t("btn.cancel", lang), "m:bc")],
        ]
    )


def admins_menu(ids: list[int], super_ids: set[int], lang: str = "zh") -> InlineKeyboardMarkup:
    rows = []
    for uid in ids:
        label = f"{uid}" + (" ★" if uid in super_ids else "")
        row = [_btn(label, "noop")]
        if uid not in super_ids:
            row.append(_btn("×", f"ad:del:{uid}"))
        rows.append(row)
    rows.append([_btn(t("btn.add", lang), "ad:add")])
    rows.append([_btn(t("btn.back", lang), "m:main")])
    return InlineKeyboardMarkup(rows)


def ui_menu(s: BotSettings, lang: str = "zh") -> InlineKeyboardMarkup:
    current = s.ui_language or "auto"
    choices = [("auto", t("ui.auto", lang)), ("zh", "中文"), ("en", "English"), ("ja", "日本語")]
    buttons = [_btn(f"{mark(current == code)} {label}", f"ui:lang:{code}") for code, label in choices]
    rows = _grid(buttons, 2)
    rows.append(
        [_btn(t("ui.forum", lang, v=on_off(s.forum_topics_enabled, lang)), "ui:forum")]
    )
    rows.append([_btn(t("btn.back", lang), "m:main")])
    return InlineKeyboardMarkup(rows)
