from app.i18n import assert_complete, format_duration, resolve_lang, t


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
