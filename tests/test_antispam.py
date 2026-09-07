from types import SimpleNamespace

from app.models import MATCH_EXACT, MATCH_REGEX, AutoReply, BotSettings
from app.services.antispam import check_message, keyword_hit
from app.services.auto_reply import match_auto_reply, parse_keyword_line
from app.services.language import detect_language


def _msg(text: str = "", **fields: object):
    base = {
        "text": text,
        "caption": None,
        "entities": [],
        "caption_entities": [],
        "forward_origin": None,
        "photo": None,
        "video": None,
        "animation": None,
        "document": None,
        "sticker": None,
        "voice": None,
        "video_note": None,
        "audio": None,
        "contact": None,
        "location": None,
        "venue": None,
    }
    base.update(fields)
    return SimpleNamespace(**base)


def test_keyword_hit() -> None:
    assert keyword_hit("免费加微 123", ["加微", "空投"]) == "加微"
    assert keyword_hit("hello", ["加微"]) is None
    assert keyword_hit("FREE AIRDROP", ["airdrop"]) == "airdrop"


def test_language_detection() -> None:
    assert detect_language("你好，我想咨询一下产品价格") == "zh"
    assert detect_language("こんにちは、元気ですか") == "ja"
    assert detect_language("안녕하세요 반갑습니다") == "ko"
    assert detect_language("это просто какой-то русский текст") == "ru"
    arabic = "هذا إعلان تجاري عن استثمار وهمي سريع"
    assert detect_language(arabic) == "ar"


def test_auto_reply_match() -> None:
    rules = [
        AutoReply(1, "价格", "contains", "请看价目表", True),
        AutoReply(2, "hello", MATCH_EXACT, "Hi", True),
        AutoReply(3, r"^id:\d+$", MATCH_REGEX, "got id", True),
        AutoReply(4, "hidden", "contains", "no", False),
    ]
    assert match_auto_reply("请问价格多少", rules).id == 1
    assert match_auto_reply("hello", rules).id == 2
    assert match_auto_reply("id:99", rules).id == 3
    assert match_auto_reply("hidden", rules) is None


def test_parse_keyword_line() -> None:
    assert parse_keyword_line("exact:Hello") == ("exact", "Hello")
    assert parse_keyword_line("regex:^a+$") == ("regex", "^a+$")
    assert parse_keyword_line("价格") == ("contains", "价格")


def test_link_filter_allowlist() -> None:
    settings = BotSettings(link_filter_enabled=True, link_block_tme=True)
    blocked = check_message(
        _msg("看这个 https://spam.shop/x"),
        settings,
        filter_keywords=[],
        allow_domains=["example.com"],
    )
    assert blocked.ok is False
    assert blocked.reason == "link"

    allowed = check_message(
        _msg("文档 https://docs.example.com/a"),
        settings,
        filter_keywords=[],
        allow_domains=["example.com"],
    )
    assert allowed.ok is True

    tme = check_message(
        _msg("加群 t.me/spamgroup"),
        settings,
        filter_keywords=[],
        allow_domains=[],
    )
    assert tme.ok is False


def test_media_and_keyword_and_language_filters() -> None:
    photo_settings = BotSettings(media_filter_enabled=True, blocked_media=["photo"])
    photo_msg = _msg("", photo=["file"])
    assert check_message(photo_msg, photo_settings, filter_keywords=[], allow_domains=[]).reason == "media"

    kw_settings = BotSettings(keyword_filter_enabled=True)
    kw = check_message(
        _msg("代理代刷加V"),
        kw_settings,
        filter_keywords=["加V"],
        allow_domains=[],
    )
    assert kw.reason == "keyword"

    lang_settings = BotSettings(language_filter_enabled=True, allowed_languages=["zh", "en"])
    lang = check_message(
        _msg("это реклама казино"),
        lang_settings,
        filter_keywords=[],
        allow_domains=[],
    )
    assert lang.reason == "language"
