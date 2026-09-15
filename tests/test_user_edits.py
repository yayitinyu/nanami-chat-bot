from types import SimpleNamespace

from app.handlers.user import has_editable_content


def test_caption_removal_remains_an_editable_media_update() -> None:
    message = SimpleNamespace(
        text=None,
        caption=None,
        animation=None,
        audio=None,
        document=None,
        photo=[object()],
        video=None,
        voice=None,
    )
    assert has_editable_content(message) is True  # type: ignore[arg-type]


def test_live_location_update_is_not_treated_as_caption_edit() -> None:
    message = SimpleNamespace(
        text=None,
        caption=None,
        animation=None,
        audio=None,
        document=None,
        photo=None,
        video=None,
        voice=None,
        location=object(),
    )
    assert has_editable_content(message) is False  # type: ignore[arg-type]
