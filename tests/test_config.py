from app.config import Config


def test_parse_admin_ids_csv(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111, 222")
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    cfg = Config()
    assert cfg.admin_ids == [111, 222]
    assert cfg.admin_chat_id is None


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
    cfg = Config()
    assert cfg.webhook_enabled is True
    assert cfg.webhook_url_path == "telegram"


def test_polling_when_no_webhook(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:AA")
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    cfg = Config()
    assert cfg.webhook_enabled is False
