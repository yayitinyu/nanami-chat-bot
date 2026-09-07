from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.models import BotSettings, FilterVerdict
from app.services.language import detect_language
from app.utils import (
    domain_matches,
    extract_mentions,
    extract_urls,
    is_telegram_link,
    media_kind,
    message_plain_text,
    normalize_domain,
    utf16_slice,
)

if TYPE_CHECKING:
    from telegram import Message


def keyword_hit(text: str, keywords: list[str]) -> str | None:
    haystack = (text or "").casefold()
    if not haystack:
        return None
    for raw in keywords:
        needle = raw.casefold().strip()
        if needle and needle in haystack:
            return raw
    return None


def check_message(
    message: Message,
    settings: BotSettings,
    *,
    filter_keywords: list[str],
    allow_domains: list[str],
) -> FilterVerdict:
    text = message_plain_text(message)

    if settings.media_filter_enabled:
        kind = media_kind(message)
        if kind and kind in settings.blocked_media:
            return FilterVerdict(False, "media", kind)

    if settings.keyword_filter_enabled:
        hit = keyword_hit(text, filter_keywords)
        if hit:
            return FilterVerdict(False, "keyword", hit)

    if settings.link_filter_enabled:
        urls = extract_urls(text)
        entities = list(message.entities or ()) + list(message.caption_entities or ())
        for ent in entities:
            if getattr(ent, "type", None) in {"url", "text_link"}:
                piece = getattr(ent, "url", None)
                if not piece and text:
                    piece = utf16_slice(text, int(ent.offset), int(ent.length))
                if piece:
                    urls.append(piece)
        for url in urls:
            domain = normalize_domain(url)
            if domain_matches(domain, allow_domains):
                continue
            if is_telegram_link(url):
                if settings.link_block_tme:
                    return FilterVerdict(False, "link", url)
                continue
            return FilterVerdict(False, "link", url)
        if settings.link_block_mentions and extract_mentions(text):
            mentions = extract_mentions(text)
            return FilterVerdict(False, "link", "@" + mentions[0])

    if settings.language_filter_enabled:
        lang = detect_language(text)
        if lang and lang not in settings.allowed_languages:
            return FilterVerdict(False, "language", lang)

    return FilterVerdict(True)


def compile_regex(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern, re.IGNORECASE | re.DOTALL)
    except re.error:
        return None
