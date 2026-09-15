from __future__ import annotations

import html
import ipaddress
import re
import unicodedata
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import idna
import regex

if TYPE_CHECKING:
    from telegram import Message
    from telegram import User as TgUser

    from app.models import User

TZ_NAME = "Asia/Shanghai"


def set_timezone(name: str) -> None:
    global TZ_NAME
    TZ_NAME = name or "Asia/Shanghai"

URL_RE = re.compile(
    r"(?i)\b(?:https?|ftp|tg)://[^\s<>\[\]()]+"
    r"|\b(?:www\.|t\.me/|telegram\.me/|telegram\.dog/)[^\s<>\[\]()]+"
    r"|\bmailto:[^\s<>\[\]()]+"
)

BARE_HOST_RE = regex.compile(
    r"(?iu)(?<![\w@])(?:"
    r"(?:\d{1,3}\.){3}\d{1,3}"
    r"|\[[0-9a-f:]+\]"
    r"|(?:(?:[^\W_]|-)+\.)+[^\W\d_](?:[^\W_]|-){1,62}"
    r")(?:\:\d{1,5})?(?:/[^\s<>\[\]()]*)?"
)

MENTION_RE = re.compile(r"(?<!\w)@([a-zA-Z][a-zA-Z0-9_]{3,31})")

DURATION_RE = re.compile(r"^\s*([0-9]{1,9})\s*([smhdw]?)\s*$", re.IGNORECASE)
MAX_DURATION_SECONDS = 365 * 86400
MAX_TELEGRAM_USER_ID = 2**63 - 1
LINK_SCAN_TIMEOUT = 0.01
_DOT_TRANSLATION = str.maketrans({"。": ".", "．": ".", "｡": "."})
_IGNORABLE_FOR_MODERATION = str.maketrans(
    {ord(ch): None for ch in ("\u00ad", "\u180e", "\u200b", "\u2060", "\ufeff")}
)

_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
    "": 60,
}


class LinkScanTimeout(ValueError):
    pass


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(TZ_NAME)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def today_key() -> str:
    return datetime.now(tz()).strftime("%Y-%m-%d")


def format_ts(ts: int | None) -> str:
    if not ts:
        return "-"
    try:
        return datetime.fromtimestamp(ts, tz()).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "-"


def parse_duration(text: str, *, max_seconds: int = MAX_DURATION_SECONDS) -> int | None:
    """Parse '30s' / '5m' / '2h' / '1d' / '1w'. Bare numbers are minutes."""
    match = DURATION_RE.match(text or "")
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    seconds = amount * _UNITS[unit]
    return seconds if 0 < seconds <= max_seconds else None


def parse_telegram_user_id(value: str) -> int | None:
    text = (value or "").strip()
    if not text.isascii() or not text.isdigit() or len(text) > 19:
        return None
    user_id = int(text)
    return user_id if 1 <= user_id <= MAX_TELEGRAM_USER_ID else None


def format_duration(seconds: int) -> str:
    from app.i18n import format_duration as localized

    return localized(seconds, "zh")


def escape(text: str | None) -> str:
    return html.escape(text or "", quote=True)


def _without_format_controls(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = normalized.translate(_IGNORABLE_FOR_MODERATION)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Cf")


def moderation_text(value: str) -> str:
    """Build a comparison-only form without changing relayed user content."""
    return _without_format_controls(value).casefold()


def display_text(value: str | None) -> str:
    """Collapse unsafe/invisible controls in untrusted UI labels."""
    normalized = unicodedata.normalize("NFKC", value or "")
    visible = "".join(
        " " if unicodedata.category(ch) in {"Cc", "Cf", "Cs"} else ch
        for ch in normalized
    )
    return " ".join(visible.split())


def display_name(user: User | TgUser) -> str:
    first = display_text(getattr(user, "first_name", None))
    last = display_text(getattr(user, "last_name", None))
    name = " ".join(p for p in (first, last) if p).strip()
    if name:
        return name
    username = getattr(user, "username", None)
    if username:
        return f"@{display_text(username)}"
    user_id = getattr(user, "user_id", None) or getattr(user, "id", None)
    return str(user_id or "")


def user_header(user: User | TgUser, extra: str = "") -> str:
    name = escape(display_name(user))
    username = display_text(getattr(user, "username", None))
    uname = f" @{escape(username)}" if username else ""
    user_id = getattr(user, "user_id", None) or getattr(user, "id", None)
    lines = [f"👤 <b>{name}</b>{uname}", f"ID: <code>{user_id}</code>"]
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    normalized = _without_format_controls(text).translate(_DOT_TRANSLATION)
    found = URL_RE.findall(normalized)
    try:
        bare_hosts = BARE_HOST_RE.findall(normalized, timeout=LINK_SCAN_TIMEOUT)
    except TimeoutError as exc:
        raise LinkScanTimeout("bare-host scan exceeded its deadline") from exc
    found.extend(item for item in bare_hosts if normalize_domain(item))
    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for item in found:
        key = item.lower().rstrip(".,;:!?)")
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def extract_mentions(text: str) -> list[str]:
    if not text:
        return []
    return [m.group(1) for m in MENTION_RE.finditer(text)]


def normalize_domain(value: str) -> str:
    raw = _without_format_controls(value).translate(_DOT_TRANSLATION).strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw if "://" in raw else f"//{raw}")
        host = parsed.hostname
    except ValueError:
        return ""
    if not host:
        return ""
    host = host.rstrip(".").lower()
    host = host.removeprefix("www.")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        ascii_host = idna.encode(host, uts46=True, std3_rules=True).decode("ascii")
    except idna.IDNAError:
        return ""
    if len(ascii_host) > 253 or "." not in ascii_host:
        return ""
    labels = ascii_host.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not re.fullmatch(r"[a-z0-9-]+", label)
        for label in labels
    ):
        return ""
    if labels[-1].isdigit():
        return ""
    return ascii_host


def is_valid_domain(value: str) -> bool:
    raw = _without_format_controls(value).translate(_DOT_TRANSLATION).strip()
    try:
        parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    except ValueError:
        return False
    return parsed.username is None and parsed.password is None and bool(
        normalize_domain(value)
    )


def domain_matches(domain: str, allowlist: list[str]) -> bool:
    domain = normalize_domain(domain)
    if not domain:
        return False
    for allowed in allowlist:
        allowed = normalize_domain(allowed)
        if allowed and (domain == allowed or domain.endswith("." + allowed)):
            return True
    return False


def is_telegram_link(url: str) -> bool:
    if (url or "").strip().lower().startswith("tg:"):
        return True
    host = normalize_domain(url)
    return host in {"t.me", "telegram.me", "telegram.dog", "telegram.org"} or host.endswith(
        ".t.me"
    )


def utf16_slice(text: str, offset: int, length: int) -> str:
    """Telegram entity offsets are UTF-16 code units."""
    encoded = text.encode("utf-16-le")
    start = offset * 2
    end = (offset + length) * 2
    return encoded[start:end].decode("utf-16-le", errors="ignore")


def message_plain_text(message: Message) -> str:
    parts: list[str] = []
    if message.text:
        parts.append(message.text)
    if message.caption:
        parts.append(message.caption)
    return "\n".join(parts)


def media_kind(message: Message) -> str | None:
    mapping = (
        ("photo", message.photo),
        ("video", message.video),
        ("animation", message.animation),
        ("document", message.document),
        ("sticker", message.sticker),
        ("voice", message.voice),
        ("video_note", message.video_note),
        ("audio", message.audio),
        ("contact", message.contact),
        ("location", message.location),
        ("venue", message.venue),
    )
    for name, value in mapping:
        if value:
            return name
    return None


def extract_media(message: Message) -> tuple[str | None, str | None, str | None]:
    """Return (media_type, file_id, text)."""
    text = message.text or message.caption
    if message.photo:
        return "photo", message.photo[-1].file_id, text
    for kind in (
        "video",
        "animation",
        "document",
        "sticker",
        "voice",
        "video_note",
        "audio",
    ):
        obj = getattr(message, kind, None)
        if obj is not None and getattr(obj, "file_id", None):
            return kind, obj.file_id, text
    return None, None, text


def page_count(total: int, per_page: int) -> int:
    if total <= 0:
        return 1
    return (total + per_page - 1) // per_page
