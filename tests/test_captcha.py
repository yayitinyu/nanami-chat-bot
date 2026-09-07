from app.services.captcha import build_button_challenge, build_math_challenge


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
