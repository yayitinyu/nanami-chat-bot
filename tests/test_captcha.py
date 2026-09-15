from urllib.parse import urlsplit

from app.services.captcha import build_button_challenge, build_math_challenge
from app.services.turnstile import (
    build_challenge_url,
    is_challenge_token,
    new_challenge_token,
)


def test_button_challenge_unique_tokens() -> None:
    winner, markup = build_button_challenge()
    tokens = []
    labels = []
    for row in markup.inline_keyboard:
        for button in row:
            labels.append(button.text)
            data = button.callback_data or ""
            assert data.startswith("c:x:")
            tokens.append(data.split(":")[2])
    assert winner in tokens
    assert len(set(tokens)) == 4
    assert labels.count("✓") == 1


def test_math_challenge_unique_tokens() -> None:
    winner, markup, prompt = build_math_challenge()
    assert "+" in prompt
    tokens = [
        (button.callback_data or "").split(":")[2]
        for row in markup.inline_keyboard
        for button in row
    ]
    assert winner in tokens
    assert len(set(tokens)) == 4


def test_turnstile_link_keeps_capability_out_of_request_url() -> None:
    challenge = new_challenge_token()
    url = build_challenge_url("https://challenge.example.com/", challenge)
    parsed = urlsplit(url)
    assert is_challenge_token(challenge)
    assert parsed.scheme == "https"
    assert parsed.netloc == "challenge.example.com"
    assert parsed.path == "/verify"
    assert parsed.query == ""
    assert parsed.fragment == challenge
