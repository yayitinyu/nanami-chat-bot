from app.i18n import assert_complete, format_duration, resolve_lang, t
from app.models import BotSettings, User
from app.texts import captcha_text, user_card


def test_catalog_complete() -> None:
    assert_complete()


def test_resolve_lang() -> None:
    assert resolve_lang("zh-CN") == "zh"
    assert resolve_lang("en-US") == "en"
    assert resolve_lang("ja") == "ja"
    assert resolve_lang("fr") == "zh"
    assert resolve_lang(None) == "zh"
    assert resolve_lang("auto") == "zh"


def test_translations_differ() -> None:
    assert t("btn.users", "zh") == "用户"
    assert t("btn.users", "en") == "Users"
    assert t("btn.users", "ja") == "ユーザー"


def test_format_duration_en() -> None:
    assert format_duration(30, "en") == "30s"
    assert format_duration(120, "en") == "2m"
    assert format_duration(3600, "en") == "1h"


def test_user_card_language_field_does_not_collide_and_is_escaped() -> None:
    user = User(
        user_id=42,
        username="alice",
        first_name="A&B",
        last_name=None,
        language_code="<en>",
        captcha_passed=True,
    )
    card = user_card(user, "en")
    assert "Language: &lt;en&gt;" in card
    assert "A&amp;B" in card


def test_captcha_panel_shows_configured_timeout() -> None:
    panel = captcha_text(BotSettings(captcha_timeout=120), "en")
    assert "Timeout\u30002m" in panel


def test_captcha_panel_shows_turnstile_type() -> None:
    panel = captcha_text(BotSettings(captcha_type="turnstile"), "en")
    assert "Type\u3000Turnstile" in panel
