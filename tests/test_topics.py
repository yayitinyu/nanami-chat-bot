from app.models import User
from app.services.topics import is_user_topic, topic_title


def test_topic_title_truncates() -> None:
    user = User(
        user_id=42,
        username="alice",
        first_name="A" * 200,
        last_name=None,
        language_code="en",
    )
    title = topic_title(user)
    assert len(title) <= 128
    assert "42" in title
    assert "@alice" in title


def test_general_topic_is_not_user() -> None:
    assert is_user_topic(1) is False
    assert is_user_topic(None) is False
    assert is_user_topic(99) is True


def test_topic_title_strips_newlines() -> None:
    user = User(1, None, "Hi\nthere", None, "zh")
    assert "\n" not in topic_title(user)
