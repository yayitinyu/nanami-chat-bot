from types import SimpleNamespace

from app.utils import (
    display_name,
    domain_matches,
    extract_mentions,
    extract_urls,
    format_duration,
    is_telegram_link,
    is_valid_domain,
    normalize_domain,
    parse_duration,
    parse_telegram_user_id,
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
    assert parse_duration("9" * 5000) is None


def test_parse_telegram_user_id() -> None:
    assert parse_telegram_user_id("123") == 123
    assert parse_telegram_user_id(" 123 ") == 123
    assert parse_telegram_user_id("0") is None
    assert parse_telegram_user_id("-1") is None
    assert parse_telegram_user_id("1" * 5000) is None


def test_untrusted_display_name_strips_controls() -> None:
    user = SimpleNamespace(
        first_name="Alice\n\u202eAdmin",
        last_name=None,
        username="alice",
        id=123,
    )
    assert display_name(user) == "Alice Admin"


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
    assert extract_urls("价格是 1.23 元") == []
    assert extract_urls("无效地址 999.999.999.999") == []


def test_domain_allowlist() -> None:
    assert domain_matches("https://cdn.example.com/a", ["example.com"])
    assert domain_matches("example.com", ["example.com"])
    assert not domain_matches("evil.com", ["example.com"])
    assert not domain_matches("example.com.evil.com", ["example.com"])
    assert normalize_domain("https://WWW.Example.COM/path") == "example.com"
    assert normalize_domain("1.23") == ""
    assert normalize_domain("https://例子.测试/path") == "xn--fsqu00a.xn--0zwm56d"
    assert normalize_domain("example。com") == "example.com"
    assert normalize_domain("faß.de") == "xn--fa-hia.de"
    assert not domain_matches("faß.de", ["fass.de"])
    assert not is_valid_domain("user@example.com")


def test_telegram_links() -> None:
    assert is_telegram_link("https://t.me/spam")
    assert is_telegram_link("telegram.me/foo")
    assert is_telegram_link("tg://resolve?domain=example")
    assert not is_telegram_link("https://example.com")


def test_duration_has_sensible_upper_bound() -> None:
    assert parse_duration("365d") == 365 * 86400
    assert parse_duration("366d") is None
