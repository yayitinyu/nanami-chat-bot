from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

DEFAULT_START_MESSAGE = "你好，请直接发送消息，管理员会尽快回复。"

MEDIA_TYPES = (
    "photo",
    "video",
    "animation",
    "document",
    "sticker",
    "voice",
    "video_note",
    "audio",
    "contact",
    "location",
    "venue",
)

LANG_LABELS: dict[str, str] = {
    "zh": "中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "ru": "俄语",
    "ar": "阿拉伯",
    "es": "西语",
    "fr": "法语",
    "de": "德语",
    "th": "泰语",
    "vi": "越南语",
    "id": "印尼语",
    "pt": "葡语",
    "tr": "土耳其",
    "hi": "印地语",
    "fa": "波斯语",
    "uk": "乌克兰",
}

MATCH_CONTAINS = "contains"
MATCH_EXACT = "exact"
MATCH_REGEX = "regex"


@dataclass
class BotSettings:
    start_message: str = DEFAULT_START_MESSAGE
    captcha_enabled: bool = False
    captcha_type: str = "button"  # button | math
    captcha_timeout: int = 120
    captcha_max_tries: int = 3
    captcha_ban_on_fail: bool = False
    rate_limit_enabled: bool = True
    rate_limit_count: int = 8
    rate_limit_window: int = 30
    rate_limit_mute: int = 300
    keyword_filter_enabled: bool = False
    language_filter_enabled: bool = False
    allowed_languages: list[str] = field(default_factory=lambda: ["zh", "en"])
    media_filter_enabled: bool = False
    blocked_media: list[str] = field(default_factory=list)
    link_filter_enabled: bool = False
    link_block_mentions: bool = False
    link_block_tme: bool = True
    notify_admin_on_filter: bool = True
    notify_user_on_filter: bool = True
    auto_reply_silent: bool = False
    ui_language: str = "auto"  # auto | zh | en | ja
    forum_topics_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BotSettings:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class User:
    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    is_banned: bool = False
    is_blocked: bool = False
    captcha_passed: bool = False
    started: bool = False
    created_at: int = 0
    last_seen_at: int = 0
    message_count: int = 0
    muted_until: int = 0
    notes: str | None = None
    forum_topic_id: int | None = None
    ui_lang: str | None = None

    @property
    def full_name(self) -> str:
        parts = [self.first_name or "", self.last_name or ""]
        name = " ".join(p for p in parts if p).strip()
        return name or (f"@{self.username}" if self.username else str(self.user_id))


@dataclass
class MessageMap:
    id: int
    user_id: int
    user_chat_id: int
    user_message_id: int
    admin_chat_id: int
    admin_message_id: int
    direction: str
    created_at: int


@dataclass
class AutoReply:
    id: int
    keyword: str
    match_type: str
    reply_text: str
    is_enabled: bool


@dataclass
class Broadcast:
    id: int
    text: str | None
    media_file_id: str | None
    media_type: str | None
    from_chat_id: int | None
    from_message_id: int | None
    interval_seconds: int | None
    last_sent_at: int | None
    next_send_at: int | None
    is_enabled: bool
    created_by: int | None
    created_at: int


@dataclass
class FilterVerdict:
    ok: bool
    reason: str | None = None
    detail: str = ""
