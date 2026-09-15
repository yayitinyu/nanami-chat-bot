import pytest
from pydantic import ValidationError

from app.config import Config
from app.main import build_application


def test_parse_admin_ids_csv(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111, 222")
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    cfg = Config()
    assert cfg.admin_ids == [111, 222]
    assert cfg.admin_chat_id is None


def test_admin_ids_are_positive_bounded_and_deduplicated(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", " 1:AA ")
    monkeypatch.setenv("ADMIN_IDS", "111, 111, 222")
    cfg = Config()
    assert cfg.bot_token == "1:AA"
    assert cfg.admin_ids == [111, 222]

    monkeypatch.setenv("ADMIN_IDS", "1" * 5000)
    with pytest.raises(ValidationError, match="positive Telegram user IDs"):
        Config()


def test_parse_admin_chat_id(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.setenv("ADMIN_CHAT_ID", "-100123")
    cfg = Config()
    assert cfg.admin_chat_id == -100123


def test_webhook_path_from_url(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.setenv("WEBHOOK_URL", "https://bot.example.com/telegram")
    monkeypatch.setenv("WEBHOOK_SECRET", "A" * 32)
    cfg = Config()
    assert cfg.webhook_enabled is True
    assert cfg.webhook_url_path == "telegram"
    assert cfg.webhook_public_url == "https://bot.example.com/telegram"


def test_webhook_path_is_appended_to_root_url(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.setenv("WEBHOOK_URL", "https://bot.example.com/")
    monkeypatch.setenv("WEBHOOK_PATH", "/custom-hook")
    monkeypatch.setenv("WEBHOOK_SECRET", "A" * 32)
    cfg = Config()
    assert cfg.webhook_url_path == "custom-hook"
    assert cfg.webhook_public_url == "https://bot.example.com/custom-hook"


def test_polling_when_no_webhook(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    cfg = Config()
    assert cfg.webhook_enabled is False


def test_application_update_queue_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.setenv("UPDATE_QUEUE_SIZE", "33")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    application = build_application(Config())
    assert application.update_queue.maxsize == 33


def test_invalid_runtime_bounds_fail_during_config_load(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.setenv("TZ", "Not/A-Timezone")
    with pytest.raises(ValidationError, match="valid IANA timezone"):
        Config()

    monkeypatch.setenv("TZ", "Asia/Shanghai")
    monkeypatch.setenv("WEBHOOK_PORT", "70000")
    with pytest.raises(ValidationError):
        Config()

    monkeypatch.setenv("WEBHOOK_PORT", "8080")
    monkeypatch.setenv("UPDATE_QUEUE_SIZE", "0")
    with pytest.raises(ValidationError):
        Config()


def test_webhook_requires_secret(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.setenv("WEBHOOK_URL", "https://bot.example.com/telegram")
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    with pytest.raises(ValidationError, match="WEBHOOK_SECRET is required"):
        Config()


@pytest.mark.parametrize(
    "url",
    [
        "http://bot.example.com/telegram",
        "https://user:pass@bot.example.com/telegram",
        "https://bot.example.com/telegram?token=leak",
        "https://bot.example.com/%0Aheader",
        "https://bad_host/telegram",
        "https://bot.example.com/%5Ctelegram",
    ],
)
def test_webhook_url_must_be_safe_https(monkeypatch, url: str) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.setenv("WEBHOOK_URL", url)
    monkeypatch.setenv("WEBHOOK_SECRET", "A" * 32)
    with pytest.raises(ValidationError, match="HTTPS URL"):
        Config()
