from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.services.turnstile import (
    TURNSTILE_ACTION,
    TurnstileUnavailable,
    content_security_policy,
    is_challenge_token,
    render_challenge_page,
    verify_turnstile_token,
)

CHALLENGE = "ts_" + "a" * 43


def _response_payload(**overrides):
    payload = {
        "success": True,
        "hostname": "challenge.example.com",
        "action": TURNSTILE_ACTION,
        "cdata": CHALLENGE,
        "error-codes": [],
    }
    payload.update(overrides)
    return payload


async def _verify(payload: dict) -> tuple[bool, tuple[str, ...]]:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["token"] == "browser-token"
        assert body["idempotency_key"]
        assert "secret" not in body
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        decision = await verify_turnstile_token(
            client,
            "https://worker.example/",
            "browser-token",
            challenge=CHALLENGE,
            expected_hostname="challenge.example.com",
        )
    return decision.passed, decision.error_codes


def test_siteverify_requires_all_bound_metadata() -> None:
    assert asyncio.run(_verify(_response_payload())) == (True, ())

    passed, codes = asyncio.run(
        _verify(_response_payload(hostname="other.example.com"))
    )
    assert not passed
    assert "hostname-mismatch" in codes

    passed, codes = asyncio.run(_verify(_response_payload(action="other")))
    assert not passed
    assert "action-mismatch" in codes

    passed, codes = asyncio.run(_verify(_response_payload(cdata="ts_wrong")))
    assert not passed
    assert "cdata-mismatch" in codes


def test_siteverify_transport_failure_is_retryable() -> None:
    async def flow() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json={"success": False})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(TurnstileUnavailable):
                await verify_turnstile_token(
                    client,
                    "https://worker.example/",
                    "browser-token",
                    challenge=CHALLENGE,
                    expected_hostname="challenge.example.com",
                )

    asyncio.run(flow())


def test_challenge_page_uses_fragment_bootstrap_and_spin_marker() -> None:
    page = render_challenge_page("public-sitekey", "csp-nonce")
    assert 'data-action="turnstile-spin-v1"' in page
    assert "api.js?render=explicit&onload=onTurnstileLoad" in page
    assert 'document.title = copy.title' in page
    assert 'document.head.appendChild(loader)' in page
    assert "window.location.hash.slice(1)" in page
    assert "history.replaceState" in page
    assert "public-sitekey" in page
    assert CHALLENGE not in page


def test_challenge_page_adapts_widget_to_narrow_mobile_viewports() -> None:
    page = render_challenge_page("public-sitekey", "csp-nonce")

    assert "min-height: 100dvh" in page
    assert "max-width: 360px" in page
    assert 'widget.getBoundingClientRect().width < 300' in page
    assert 'size: compact ? "compact" : "flexible"' in page
    assert "#turnstile-widget.is-compact { min-height: 140px; }" in page


def test_challenge_token_and_csp_are_strict() -> None:
    assert is_challenge_token(CHALLENGE)
    assert not is_challenge_token("ts_short")
    policy = content_security_policy("nonce", turnstile=True)
    assert "https://challenges.cloudflare.com" in policy
    assert "frame-ancestors 'none'" in policy
    assert "form-action 'self'" in policy
