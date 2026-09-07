from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from telegram import Message, User as TgUser

    from app.models import User

TZ_NAME = "Asia/Shanghai"


def set_timezone(name: str) -> None:
    global TZ_NAME
    TZ_NAME = name or "Asia/Shanghai"

URL_RE = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>\[\]()]+"
    r"|(?:t\.me|telegram\.me|telegram\.dog)/[^\s<>\[\]()]+"
)

BARE_DOMAIN_RE = re.compile(
    r"(?i)\b(?:[a-z0-9-]+\.)+(?:com|net|org|xyz|top|info|io|cc|me|co|cn|ru|"
    r"tk|ml|ga|cf|gq|shop|vip|club|online|site|click|pro|biz|tv|gg|dev|"
    r"app|link|live|news|store|icu|cyou|sbs|bond|cfd|rest|quest|zip)\b"
)

MENTION_RE = re.compile(r"(?<!\w)@([a-zA-Z][a-zA-Z0-9_]{3,31})")

DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhdw]?)\s*$", re.IGNORECASE)

_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
    "": 60,
}


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(TZ_NAME)
    except Exception:
        return ZoneInfo("UTC")


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def today_key() -> str:
    return datetime.now(tz()).strftime("%Y-%m-%d")


def format_ts(ts: int | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts, tz()).strftime("%Y-%m-%d %H:%M")


def parse_duration(text: str) -> int | None:
    """Parse '30s' / '5m' / '2h' / '1d' / '1w'. Bare numbers are minutes."""
    match = DURATION_RE.match(text or "")
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    seconds = amount * _UNITS[unit]
    return seconds if seconds > 0 else None


def format_duration(seconds: int) -> str:
    from app.i18n import format_duration as localized

    return localized(seconds, "zh")


def escape(text: str | None) -> str:
    return html.escape(text or "", quote=True)


def display_name(user: User | TgUser) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    name = " ".join(p for p in (first, last) if p).strip()
    if name:
        return name
    username = getattr(user, "username", None)
    if username:
        return f"@{username}"
    user_id = getattr(user, "user_id", None) or getattr(user, "id", None)
    return str(user_id or "")


def user_header(user: User | TgUser, extra: str = "") -> str:
    name = escape(display_name(user))
    username = getattr(user, "username", None)
    uname = f" @{escape(username)}" if username else ""
    user_id = getattr(user, "user_id", None) or getattr(user, "id")
    lines = [f"👤 <b>{name}</b>{uname}", f"ID: <code>{user_id}</code>"]
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    found = URL_RE.findall(text)
    found.extend(BARE_DOMAIN_RE.findall(text))
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
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0]
    value = value.split("?")[0]
    if ":" in value and not value.count(":") > 1:
        host, port = value.rsplit(":", 1)
        if port.isdigit():
            value = host
    if value.startswith("www."):
        value = value[4:]
    return value


def domain_matches(domain: str, allowlist: list[str]) -> bool:
    domain = normalize_domain(domain)
    for allowed in allowlist:
        allowed = normalize_domain(allowed)
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False


def is_telegram_link(url: str) -> bool:
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
