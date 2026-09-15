from __future__ import annotations

import time
from functools import lru_cache

import regex

from app.models import MATCH_CONTAINS, MATCH_EXACT, MATCH_REGEX, AutoReply
from app.utils import moderation_text

MAX_AUTO_REPLY_PATTERN = 256
MAX_AUTO_REPLY_TEXT = 4096
AUTO_REPLY_TOTAL_TIMEOUT = 0.05
AUTO_REPLY_PATTERN_TIMEOUT = 0.02


@lru_cache(maxsize=256)
def _compiled(pattern: str) -> regex.Pattern | None:
    try:
        return regex.compile(pattern, regex.IGNORECASE | regex.DOTALL)
    except regex.error:
        return None


def valid_auto_reply_keyword(match_type: str, keyword: str) -> bool:
    if not keyword or len(keyword) > MAX_AUTO_REPLY_PATTERN:
        return False
    return match_type != MATCH_REGEX or _compiled(keyword) is not None


def match_auto_reply(text: str, rules: list[AutoReply]) -> AutoReply | None:
    if not text:
        return None
    candidate = text[:MAX_AUTO_REPLY_TEXT]
    folded = moderation_text(candidate)
    deadline = time.monotonic() + AUTO_REPLY_TOTAL_TIMEOUT
    for rule in rules:
        if not rule.is_enabled:
            continue
        keyword = rule.keyword
        if rule.match_type == MATCH_EXACT:
            if folded.strip() == moderation_text(keyword).strip():
                return rule
        elif rule.match_type == MATCH_REGEX:
            pattern = _compiled(keyword)
            remaining = deadline - time.monotonic()
            if pattern is None or remaining <= 0:
                continue
            try:
                if pattern.search(
                    candidate,
                    timeout=min(AUTO_REPLY_PATTERN_TIMEOUT, remaining),
                ):
                    return rule
            except TimeoutError:
                continue
        else:
            if moderation_text(keyword) in folded:
                return rule
    return None


def parse_keyword_line(text: str) -> tuple[str, str]:
    """Parse optional prefix: 'exact:hi' / 'regex:^hi' / 'contains:hi' / 'hi'."""
    raw = (text or "").strip()
    lower = raw.lower()
    for prefix, kind in (
        ("exact:", MATCH_EXACT),
        ("regex:", MATCH_REGEX),
        ("contains:", MATCH_CONTAINS),
    ):
        if lower.startswith(prefix):
            return kind, raw[len(prefix) :].strip()
    return MATCH_CONTAINS, raw
