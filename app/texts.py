from __future__ import annotations

from app.i18n import format_duration, media_label, t
from app.models import LANG_LABELS, BotSettings, User
from app.utils import display_name, display_text, escape, format_ts, now_ts


def on_off(value: bool, lang: str = "zh") -> str:
    return t("on" if value else "off", lang)


def mark(value: bool) -> str:
    return "✓" if value else "·"


def start_message_for(settings: BotSettings, lang: str) -> str:
    custom = settings.start_message
    if not custom or custom == t("start.default", "zh"):
        return t("start.default", lang)
    return custom


def main_text(total: int, banned: int, active: int, today: dict[str, int], lang: str = "zh") -> str:
    return (
        f"{t('menu.title', lang)}\n\n"
        + t(
            "menu.stats",
            lang,
            total=total,
            active=active,
            banned=banned,
            messages=today.get("messages_in", 0),
            filtered=today.get("filtered", 0),
        )
    )


def user_card(user: User, lang: str = "zh") -> str:
    status = []
    if user.is_banned:
        status.append(t("user.status.banned", lang))
    if user.is_blocked:
        status.append(t("user.status.blocked", lang))
    if user.muted_until > now_ts():
        status.append(t("user.status.muted", lang, until=format_ts(user.muted_until)))
    if not user.captcha_passed:
        status.append(t("user.status.unverified", lang))
    if not status:
        status.append(t("user.status.ok", lang))
    uname = f"@{escape(display_text(user.username))}" if user.username else "-"
    notes = t("user.notes", lang, notes=escape(user.notes)) if user.notes else ""
    return t(
        "user.card",
        lang,
        name=escape(display_name(user)),
        uname=uname,
        id=user.user_id,
        status=" · ".join(status),
        language=escape(user.language_code or "-"),
        created=format_ts(user.created_at),
        seen=format_ts(user.last_seen_at),
        count=user.message_count,
        notes=notes,
    )


def start_preview(settings: BotSettings, lang: str = "zh") -> str:
    body = escape((settings.start_message or t("empty", lang))[:800])
    return f"{t('start.title', lang)}\n\n{body}\n\n{t('start.help', lang)}"


def antispam_overview(s: BotSettings, lang: str = "zh") -> str:
    oo = lambda v: on_off(v, lang)
    return (
        f"{t('spam.title', lang)}\n\n"
        f"{t('spam.captcha', lang, v=oo(s.captcha_enabled))}\n"
        f"{t('spam.rate', lang, v=oo(s.rate_limit_enabled))}\n"
        f"{t('spam.keyword', lang, v=oo(s.keyword_filter_enabled))}\n"
        f"{t('spam.language', lang, v=oo(s.language_filter_enabled))}\n"
        f"{t('spam.media', lang, v=oo(s.media_filter_enabled))}\n"
        f"{t('spam.link', lang, v=oo(s.link_filter_enabled))}"
    )


def captcha_text(s: BotSettings, lang: str = "zh") -> str:
    kind = t("captcha.type.button" if s.captcha_type == "button" else "captcha.type.math", lang)
    return (
        f"{t('captcha.title', lang)}\n\n"
        f"{t('captcha.switch', lang, v=on_off(s.captcha_enabled, lang))}\n"
        f"{t('captcha.type', lang, v=kind)}\n"
        f"{t('captcha.timeout', lang, v=format_duration(s.captcha_timeout, lang))}\n"
        f"{t('captcha.tries', lang, v=s.captcha_max_tries)}\n"
        f"{t('captcha.ban_fail', lang, v=on_off(s.captcha_ban_on_fail, lang))}"
    )


def rate_text(s: BotSettings, lang: str = "zh") -> str:
    return (
        f"{t('rate.title', lang)}\n\n"
        + t(
            "rate.body",
            lang,
            v=on_off(s.rate_limit_enabled, lang),
            count=s.rate_limit_count,
            window=format_duration(s.rate_limit_window, lang),
            mute=format_duration(s.rate_limit_mute, lang),
        )
    )


def language_text(s: BotSettings, lang: str = "zh") -> str:
    allowed = "、".join(LANG_LABELS.get(c, c) for c in s.allowed_languages) or t("none", lang)
    return (
        f"{t('lang_filter.title', lang)}\n\n"
        + t(
            "lang_filter.body",
            lang,
            v=on_off(s.language_filter_enabled, lang),
            allowed=allowed,
        )
    )


def media_text(s: BotSettings, lang: str = "zh") -> str:
    blocked = (
        "、".join(media_label(k, lang) for k in s.blocked_media) if s.blocked_media else t("none", lang)
    )
    return (
        f"{t('media.title', lang)}\n\n"
        + t(
            "media.body",
            lang,
            v=on_off(s.media_filter_enabled, lang),
            blocked=blocked,
        )
    )


def link_text(s: BotSettings, domains: list[str], lang: str = "zh") -> str:
    allow = "\n".join(f"· {escape(d)}" for d in domains[:15]) if domains else t("empty", lang)
    return (
        f"{t('link.title', lang)}\n\n"
        + t(
            "link.body",
            lang,
            v=on_off(s.link_filter_enabled, lang),
            mentions=on_off(s.link_block_mentions, lang),
            tme=on_off(s.link_block_tme, lang),
            allow=allow,
        )
    )


def keyword_filter_text(s: BotSettings, keywords: list[str], lang: str = "zh") -> str:
    body = "\n".join(f"· {escape(k)}" for k in keywords[:20]) if keywords else t("empty", lang)
    return (
        f"{t('kw_filter.title', lang)}\n\n"
        + t("kw_filter.body", lang, v=on_off(s.keyword_filter_enabled, lang), body=body)
    )


def auto_reply_text(items: list[tuple[int, str, str, bool]], lang: str = "zh") -> str:
    if not items:
        body = t("ar.empty", lang)
    else:
        lines = []
        for item_id, keyword, match_type, enabled in items[:20]:
            flag = on_off(enabled, lang)
            lines.append(f"{item_id}. [{flag}|{escape(match_type)}] {escape(keyword)}")
        body = "\n".join(lines)
    return f"{t('ar.title', lang)}\n\n{body}"


def broadcast_list_text(items: list[tuple[int, str, bool, str]], lang: str = "zh") -> str:
    if not items:
        body = t("bc.empty", lang)
    else:
        lines = []
        for item_id, summary, enabled, interval in items[:12]:
            flag = on_off(enabled, lang)
            lines.append(f"{item_id}. [{flag}] {escape(interval)} · {escape(summary)}")
        body = "\n".join(lines)
    return f"{t('bc.title', lang)}\n\n{t('bc.help', lang)}\n\n{body}"


def ui_text(s: BotSettings, lang: str = "zh") -> str:
    if s.ui_language == "auto":
        current = t("ui.auto", lang)
    else:
        current = {"zh": "中文", "en": "English", "ja": "日本語"}.get(s.ui_language, s.ui_language)
    return (
        f"{t('ui.title', lang)}\n\n"
        f"{t('ui.lang', lang, v=current)}\n"
        f"{t('ui.forum', lang, v=on_off(s.forum_topics_enabled, lang))}\n\n"
        f"{t('ui.forum.help', lang)}"
    )
