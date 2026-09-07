from app.utils import (
    domain_matches,
    extract_mentions,
    extract_urls,
    format_duration,
    is_telegram_link,
    normalize_domain,
    parse_duration,
)


def test_parse_duration() -> None:
    assert parse_duration("30s") == 30
    assert parse_duration("5m") == 300
    assert parse_duration("2h") == 7200
    assert parse_duration("1d") == 86400
    assert parse_duration("1w") == 604800
    assert parse_duration("15") == 900
    assert parse_duration("0m") is None
    assert parse_duration("abc") is None


def test_format_duration() -> None:
    assert format_duration(30) == "30秒"
    assert format_duration(120) == "2分钟"
    assert format_duration(3600) == "1小时"


def test_extract_urls_and_mentions() -> None:
    text = "see https://spam.example/x and www.foo.com and t.me/joinchat/abc @CryptoKing"
    urls = extract_urls(text)
    assert any("spam.example" in u for u in urls)
    assert any("foo.com" in u for u in urls)
    assert any("t.me/joinchat/abc" in u for u in urls)
    assert extract_mentions(text) == ["CryptoKing"]


def test_domain_allowlist() -> None:
    assert domain_matches("https://cdn.example.com/a", ["example.com"])
    assert domain_matches("example.com", ["example.com"])
    assert not domain_matches("evil.com", ["example.com"])
    assert not domain_matches("example.com.evil.com", ["example.com"])
    assert normalize_domain("https://WWW.Example.COM/path") == "example.com"


def test_telegram_links() -> None:
    assert is_telegram_link("https://t.me/spam")
    assert is_telegram_link("telegram.me/foo")
    assert not is_telegram_link("https://example.com")
