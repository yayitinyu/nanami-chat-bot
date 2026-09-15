from __future__ import annotations

import html
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.i18n import UI_LANGS, t

TURNSTILE_ACTION = "turnstile-spin-v1"
TURNSTILE_KIND = "turnstile"
_CHALLENGE_RE = re.compile(r"ts_[A-Za-z0-9_-]{32,128}\Z")


class TurnstileUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class TurnstileDecision:
    passed: bool
    error_codes: tuple[str, ...] = ()


def new_challenge_token() -> str:
    return f"ts_{secrets.token_urlsafe(32)}"


def is_challenge_token(value: str) -> bool:
    return bool(_CHALLENGE_RE.fullmatch(value))


def build_challenge_url(public_url: str, challenge: str) -> str:
    if not is_challenge_token(challenge):
        raise ValueError("invalid Turnstile challenge token")
    # A fragment is not sent to the origin or included in normal access logs.
    return f"{public_url.rstrip('/')}/verify#{quote(challenge, safe='_-')}"


async def verify_turnstile_token(
    client: httpx.AsyncClient,
    verify_url: str,
    response_token: str,
    *,
    challenge: str,
    expected_hostname: str,
) -> TurnstileDecision:
    if not response_token or len(response_token) > 2048:
        return TurnstileDecision(False, ("invalid-input-response",))
    if not is_challenge_token(challenge):
        return TurnstileDecision(False, ("invalid-cdata",))

    idempotency_key = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"nanami-chat-bot:{challenge}:{response_token}",
        )
    )
    try:
        response = await client.post(
            verify_url,
            json={
                "token": response_token,
                "idempotency_key": idempotency_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TurnstileUnavailable("siteverify Worker request failed") from exc

    if not isinstance(payload, dict):
        raise TurnstileUnavailable("siteverify Worker returned invalid JSON")

    raw_codes = payload.get("error-codes", [])
    error_codes = (
        tuple(str(code) for code in raw_codes)
        if isinstance(raw_codes, list)
        else ("invalid-response-shape",)
    )
    checks = (
        payload.get("success") is True,
        payload.get("hostname") == expected_hostname,
        payload.get("action") == TURNSTILE_ACTION,
        payload.get("cdata") == challenge,
    )
    if all(checks):
        return TurnstileDecision(True)

    if payload.get("success") is True:
        if payload.get("hostname") != expected_hostname:
            error_codes += ("hostname-mismatch",)
        if payload.get("action") != TURNSTILE_ACTION:
            error_codes += ("action-mismatch",)
        if payload.get("cdata") != challenge:
            error_codes += ("cdata-mismatch",)
    return TurnstileDecision(False, error_codes or ("invalid-input-response",))


_PAGE_STYLE = """
:root {
  color-scheme: light dark;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  background: #f3f4f6;
  color: #202124;
}
*, *::before, *::after { box-sizing: border-box; }
html { min-width: 0; }
body {
  width: 100%;
  min-width: 0;
  min-height: 100vh;
  min-height: 100dvh;
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-x: hidden;
  padding:
    max(20px, env(safe-area-inset-top))
    max(12px, env(safe-area-inset-right))
    max(20px, env(safe-area-inset-bottom))
    max(12px, env(safe-area-inset-left));
}
main {
  width: 100%;
  max-width: 360px;
  min-width: 0;
  padding: clamp(14px, 5vw, 26px);
  border: 1px solid rgba(127, 127, 127, 0.22);
  border-radius: 16px;
  background: #fcfcfd;
  box-shadow: 0 16px 44px rgba(45, 52, 64, 0.09);
}
h1 {
  margin: 0 0 20px;
  font-size: 1.25rem;
  line-height: 1.3;
  letter-spacing: -0.01em;
}
form {
  min-width: 0;
  display: grid;
  gap: 16px;
}
#turnstile-widget {
  width: 100%;
  min-width: 0;
  min-height: 65px;
  display: flex;
  align-items: center;
  justify-content: center;
}
#turnstile-widget.is-compact { min-height: 140px; }
button {
  width: 100%;
  min-height: 48px;
  padding: 0 18px;
  border: 0;
  border-radius: 12px;
  background: #202124;
  color: #fafafa;
  font: inherit;
  font-weight: 650;
  line-height: 1;
  cursor: pointer;
}
button:disabled { cursor: default; opacity: 0.42; }
button:focus-visible {
  outline: 3px solid rgba(32, 33, 36, 0.28);
  outline-offset: 3px;
}
button:active:not(:disabled) { transform: translateY(1px); }
[role="alert"] {
  margin: 0 0 18px;
  color: #b42318;
  font-size: 0.9375rem;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.success { color: #067647; }
[hidden] { display: none !important; }
@media (max-height: 480px) {
  body { align-items: flex-start; }
}
@media (prefers-color-scheme: dark) {
  :root { background: #111317; color: #f5f5f6; }
  main {
    border-color: rgba(255, 255, 255, 0.12);
    background: #1a1c21;
    box-shadow: 0 16px 44px rgba(4, 6, 10, 0.22);
  }
  button { background: #f5f5f6; color: #1a1c21; }
  button:focus-visible { outline-color: rgba(245, 245, 246, 0.32); }
}
""".strip()


def _script_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def render_challenge_page(
    sitekey: str,
    csp_nonce: str,
    *,
    challenge: str | None = None,
    initial_state: str = "ready",
) -> str:
    copy = {
        lang: {
            "title": t("turnstile.web.title", lang),
            "submit": t("turnstile.web.submit", lang),
            "invalid": t("turnstile.web.invalid", lang),
            "failed": t("turnstile.web.failed", lang),
            "unavailable": t("turnstile.web.unavailable", lang),
        }
        for lang in UI_LANGS
    }
    script = """
(() => {
  const copies = __COPY__;
  const browserLanguage = (navigator.language || "").toLowerCase();
  const language = browserLanguage.startsWith("ja")
    ? "ja"
    : browserLanguage.startsWith("en") ? "en" : "zh";
  const copy = copies[language];
  document.documentElement.lang = language;
  document.title = copy.title;
  document.querySelector("h1").textContent = copy.title;
  const form = document.querySelector("form");
  const submit = document.querySelector("button");
  const message = document.querySelector("[role=alert]");
  submit.textContent = copy.submit;

  const show = (text) => {
    message.textContent = text;
    message.hidden = false;
  };
  let fromFragment = "";
  try {
    fromFragment = decodeURIComponent(window.location.hash.slice(1));
  } catch (_) {
    fromFragment = "";
  }
  const challenge = __CHALLENGE__ || fromFragment;
  try {
    history.replaceState(null, "", window.location.pathname);
  } catch (_) {}

  if (!/^ts_[A-Za-z0-9_-]{32,128}$/.test(challenge)) {
    show(copy.invalid);
    return;
  }
  document.querySelector("input[name=challenge]").value = challenge;
  form.hidden = false;
  const initialState = __STATE__;
  if (initialState === "failed") show(copy.failed);
  if (initialState === "unavailable") show(copy.unavailable);

  window.onTurnstileLoad = () => {
    const widget = document.querySelector("#turnstile-widget");
    const compact = widget.getBoundingClientRect().width < 300;
    widget.classList.toggle("is-compact", compact);
    window.turnstile.render("#turnstile-widget", {
      sitekey: __SITEKEY__,
      action: "turnstile-spin-v1",
      cData: challenge,
      size: compact ? "compact" : "flexible",
      theme: "auto",
      callback: () => { submit.disabled = false; },
      "expired-callback": () => { submit.disabled = true; },
      "timeout-callback": () => { submit.disabled = true; },
      "error-callback": () => { submit.disabled = true; show(copy.unavailable); },
      "unsupported-callback": () => { submit.disabled = true; show(copy.unavailable); }
    });
  };
  const loader = document.createElement("script");
  loader.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=onTurnstileLoad";
  loader.async = true;
  loader.defer = true;
  document.head.appendChild(loader);
})();
"""
    script = (
        script.replace("__COPY__", _script_json(copy))
        .replace("__CHALLENGE__", _script_json(challenge))
        .replace("__STATE__", _script_json(initial_state))
        .replace("__SITEKEY__", _script_json(sitekey))
    )
    escaped_nonce = html.escape(csp_nonce, quote=True)
    escaped_sitekey = html.escape(sitekey, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Verification</title>
  <style nonce="{escaped_nonce}">{_PAGE_STYLE}</style>
</head>
<body>
  <main>
    <h1>Verification</h1>
    <p role="alert" hidden></p>
    <form method="post" action="/verify" hidden>
      <input type="hidden" name="challenge">
      <div id="turnstile-widget" data-sitekey="{escaped_sitekey}"
           data-action="{TURNSTILE_ACTION}"></div>
      <button type="submit" disabled>Verify</button>
    </form>
  </main>
  <script nonce="{escaped_nonce}">{script}</script>
</body>
</html>"""


def render_result_page(lang: str, csp_nonce: str, *, success: bool) -> str:
    key = "turnstile.web.success" if success else "turnstile.web.invalid"
    css_class = "success" if success else ""
    escaped_nonce = html.escape(csp_nonce, quote=True)
    return f"""<!doctype html>
<html lang="{html.escape(lang, quote=True)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(t('turnstile.web.title', lang))}</title>
  <style nonce="{escaped_nonce}">{_PAGE_STYLE}</style>
</head>
<body>
  <main>
    <h1>{html.escape(t('turnstile.web.title', lang))}</h1>
    <p role="alert" class="{css_class}">{html.escape(t(key, lang))}</p>
  </main>
</body>
</html>"""


def content_security_policy(csp_nonce: str, *, turnstile: bool) -> str:
    script_sources = f"'nonce-{csp_nonce}'"
    frame_sources = "'none'"
    connect_sources = "'self'"
    if turnstile:
        script_sources += " 'strict-dynamic' https://challenges.cloudflare.com"
        frame_sources = "https://challenges.cloudflare.com"
        connect_sources += " https://challenges.cloudflare.com"
    return "; ".join(
        (
            "default-src 'none'",
            f"script-src {script_sources}",
            f"style-src 'nonce-{csp_nonce}'",
            f"frame-src {frame_sources}",
            f"connect-src {connect_sources}",
            "img-src data:",
            "form-action 'self'",
            "base-uri 'none'",
            "object-src 'none'",
            "frame-ancestors 'none'",
        )
    )
