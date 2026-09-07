from __future__ import annotations

import re

from app.models import MATCH_CONTAINS, MATCH_EXACT, MATCH_REGEX, AutoReply


def match_auto_reply(text: str, rules: list[AutoReply]) -> AutoReply | None:
    if not text:
        return None
    folded = text.casefold()
    for rule in rules:
        if not rule.is_enabled:
            continue
        keyword = rule.keyword
        if rule.match_type == MATCH_EXACT:
            if folded.strip() == keyword.casefold():
                return rule
        elif rule.match_type == MATCH_REGEX:
            try:
                if re.search(keyword, text, re.IGNORECASE | re.DOTALL):
                    return rule
            except re.error:
                continue
        else:
            if keyword.casefold() in folded:
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
