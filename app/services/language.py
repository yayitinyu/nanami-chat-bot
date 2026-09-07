from __future__ import annotations

import re
from collections import Counter

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

_LETTERS = re.compile(r"[^\W\d_]+", re.UNICODE)

SCRIPT_RANGES: list[tuple[str, int, int]] = [
    ("han", 0x4E00, 0x9FFF),
    ("han", 0x3400, 0x4DBF),
    ("hira", 0x3040, 0x309F),
    ("kata", 0x30A0, 0x30FF),
    ("hangul", 0xAC00, 0xD7AF),
    ("cyrillic", 0x0400, 0x04FF),
    ("arabic", 0x0600, 0x06FF),
    ("thai", 0x0E00, 0x0E7F),
    ("devanagari", 0x0900, 0x097F),
    ("latin", 0x0041, 0x007A),
    ("latin", 0x00C0, 0x024F),
]

SCRIPT_LANG = {
    "han": "zh",
    "hira": "ja",
    "kata": "ja",
    "hangul": "ko",
    "cyrillic": "ru",
    "arabic": "ar",
    "thai": "th",
    "devanagari": "hi",
    "latin": "en",
}

# langdetect sometimes returns zh-cn / zh-tw
LANG_NORMALIZE = {
    "zh-cn": "zh",
    "zh-tw": "zh",
    "zh-cy": "zh",
}


def _script_of(char: str) -> str | None:
    code = ord(char)
    for name, start, end in SCRIPT_RANGES:
        if start <= code <= end:
            return name
    return None


def script_counts(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for char in text:
        script = _script_of(char)
        if script:
            counts[script] += 1
    return counts


def detect_language(text: str) -> str | None:
    """Best-effort language id (zh/en/ja/...). None if unknown/too short."""
    cleaned = "".join(_LETTERS.findall(text or ""))
    if not cleaned:
        # still count CJK etc. from original (letters regex may drop them? \w includes CJK)
        cleaned = re.sub(r"[\s\d\W_]+", "", text or "", flags=re.UNICODE)
    if len(cleaned) < 2:
        return None

    counts = script_counts(cleaned)
    total = sum(counts.values())
    if total == 0:
        return None

    hira_kata = counts["hira"] + counts["kata"]
    if hira_kata >= 2 or (hira_kata >= 1 and counts["han"] >= 1):
        return "ja"
    if counts["hangul"] >= 2:
        return "ko"
    if counts["arabic"] / total >= 0.3:
        return "ar"
    if counts["cyrillic"] / total >= 0.3:
        return "ru"
    if counts["thai"] / total >= 0.3:
        return "th"
    if counts["devanagari"] / total >= 0.3:
        return "hi"
    if counts["han"] / total >= 0.3:
        return "zh"

    if len(cleaned) >= 12:
        try:
            raw = detect(text)
            return LANG_NORMALIZE.get(raw, raw.split("-")[0])
        except LangDetectException:
            pass

    if counts["latin"] / total >= 0.5:
        return "en"
    return None
