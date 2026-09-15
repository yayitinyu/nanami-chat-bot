from __future__ import annotations

import logging
import secrets
from typing import Any, cast

import httpx
from telegram.error import TelegramError
from telegram.ext import Application as TelegramApplication
from tornado.httpserver import HTTPServer
from tornado.web import Application as TornadoApplication
from tornado.web import RequestHandler

from app.config import Config
from app.db import Database
from app.i18n import t
from app.models import BotSettings, User
from app.services.turnstile import (
    TurnstileUnavailable,
    content_security_policy,
    is_challenge_token,
    render_challenge_page,
    render_result_page,
    verify_turnstile_token,
)
from app.texts import start_message_for
from app.utils import now_ts

log = logging.getLogger(__name__)
MAX_CHALLENGE_BODY = 16 * 1024


def _log_request(handler: RequestHandler) -> None:
    status = handler.get_status()
    method = handler.request.method
    # request.path deliberately excludes the short-lived capability fragment/body.
    path = handler.request.path
    if status >= 500:
        log.error("challenge request %s %s -> %s", method, path, status)
    elif status >= 400:
        log.warning("challenge request %s %s -> %s", method, path, status)


class ChallengeServer:
    def __init__(self, application: TelegramApplication, config: Config) -> None:
        if not config.turnstile_configured:
            raise ValueError("Turnstile is not configured")
        self.application = application
        self.config = config
        self.sitekey = cast(str, config.turnstile_sitekey)
        self.verify_url = cast(str, config.turnstile_verify_url)
        self.expected_hostname = cast(str, config.challenge_hostname)
        self._client: httpx.AsyncClient | None = None
        self._server: HTTPServer | None = None

    @property
    def database(self) -> Database:
        return self.application.bot_data["db"]

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("challenge server is not started")
        return self._client

    async def start(self) -> None:
        if self._server is not None:
            return
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            follow_redirects=False,
            headers={"User-Agent": "nanami-chat-bot/turnstile"},
        )
        web_app = TornadoApplication(
            [
                (r"/verify", VerifyHandler, {"service": self}),
                (r"/healthz", HealthHandler),
            ],
            default_handler_class=NotFoundHandler,
            log_function=_log_request,
            debug=False,
            autoreload=False,
        )
        server = HTTPServer(
            web_app,
            xheaders=False,
            max_body_size=MAX_CHALLENGE_BODY,
            decompress_request=False,
        )
        try:
            server.listen(
                self.config.challenge_port,
                address=self.config.challenge_listen,
            )
        except BaseException:
            await self._client.aclose()
            self._client = None
            raise
        self._server = server

    async def close(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.stop()
            await server.close_all_connections()
        client = self._client
        self._client = None
        if client is not None:
            await client.aclose()


class BaseHandler(RequestHandler):
    def set_default_headers(self) -> None:
        self.set_header("Cache-Control", "no-store, max-age=0")
        self.set_header("Referrer-Policy", "no-referrer")
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("X-Frame-Options", "DENY")
        self.set_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )

    def write_html(
        self,
        body: str,
        *,
        csp_nonce: str,
        turnstile: bool,
        status: int = 200,
    ) -> None:
        self.set_status(status)
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.set_header(
            "Content-Security-Policy",
            content_security_policy(csp_nonce, turnstile=turnstile),
        )
        self.finish(body)


class HealthHandler(BaseHandler):
    def get(self) -> None:
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.finish({"ok": True, "service": "turnstile-challenge"})


class NotFoundHandler(BaseHandler):
    def prepare(self) -> None:
        self.set_status(404)
        self.set_header("Content-Type", "text/plain; charset=utf-8")
        self.finish("Not found")


class VerifyHandler(BaseHandler):
    def initialize(self, service: ChallengeServer) -> None:
        self.service = service

    def get(self) -> None:
        nonce = secrets.token_urlsafe(18)
        self.write_html(
            render_challenge_page(self.service.sitekey, nonce),
            csp_nonce=nonce,
            turnstile=True,
        )

    async def post(self) -> None:
        content_type = self.request.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/x-www-form-urlencoded"):
            self._write_result("zh", success=False, status=415)
            return
        challenges = self.get_body_arguments("challenge", strip=True)
        responses = self.get_body_arguments("cf-turnstile-response", strip=True)
        if len(challenges) != 1 or len(responses) != 1:
            self._write_result("zh", success=False, status=400)
            return
        challenge = challenges[0]
        response_token = responses[0]
        if not is_challenge_token(challenge) or not response_token:
            self._write_result("zh", success=False, status=400)
            return
        try:
            await self._process(challenge, response_token)
        except Exception:
            log.exception("unexpected Turnstile challenge processing failure")
            self._write_challenge(challenge, state="unavailable", status=503)

    async def _process(self, challenge: str, response_token: str) -> None:
        current = now_ts()
        state, user_id, _tries = await self.service.database.get_turnstile_challenge(
            challenge, current
        )
        if state != "active" or user_id is None:
            self._write_result("zh", success=False, status=410)
            return
        user = await self.service.database.get_user(user_id)
        if user is None or user.is_banned:
            await self.service.database.delete_captcha(user_id)
            self._write_result(_user_language(user), success=False, status=410)
            return
        if user.captcha_passed:
            await self.service.database.delete_captcha(user_id)
            self._write_result(_user_language(user), success=True)
            return

        try:
            decision = await verify_turnstile_token(
                self.service.client,
                self.service.verify_url,
                response_token,
                challenge=challenge,
                expected_hostname=self.service.expected_hostname,
            )
        except TurnstileUnavailable:
            log.warning("Turnstile siteverify Worker is unavailable")
            self._write_challenge(challenge, state="unavailable", status=503)
            return

        settings: BotSettings = self.service.application.bot_data[
            "settings_svc"
        ].current
        outcome, applied_user_id, _tries = (
            await self.service.database.apply_turnstile_attempt(
                challenge,
                now_ts(),
                decision.passed,
                settings.captcha_max_tries,
            )
        )
        if outcome == "passed" and applied_user_id is not None:
            await _record_stat(self.service.database, "captcha_pass")
            try:
                await _notify_success(self.service.application, user, settings)
            except Exception:
                # Verification is already committed; a Telegram delivery failure
                # must not tell the browser that the security decision failed.
                log.exception(
                    "Turnstile passed but the Telegram success notification failed"
                )
            self._write_result(_user_language(user), success=True)
            return
        if outcome == "failed":
            await _record_stat(self.service.database, "captcha_fail")
            self._write_challenge(challenge, state="failed", status=422)
            return
        if outcome == "exhausted" and applied_user_id is not None:
            await _record_stat(self.service.database, "captcha_fail")
            await _apply_failure_penalty(
                self.service.application,
                user,
                settings,
                now_ts(),
            )
            self._write_result(_user_language(user), success=False, status=429)
            return
        self._write_result(_user_language(user), success=False, status=410)

    def _write_challenge(self, challenge: str, *, state: str, status: int) -> None:
        nonce = secrets.token_urlsafe(18)
        self.write_html(
            render_challenge_page(
                self.service.sitekey,
                nonce,
                challenge=challenge,
                initial_state=state,
            ),
            csp_nonce=nonce,
            turnstile=True,
            status=status,
        )

    def _write_result(self, lang: str, *, success: bool, status: int = 200) -> None:
        nonce = secrets.token_urlsafe(18)
        self.write_html(
            render_result_page(lang, nonce, success=success),
            csp_nonce=nonce,
            turnstile=False,
            status=status,
        )


def _user_language(user: User | None) -> str:
    if user is None:
        return "zh"
    code = user.language_code or user.ui_lang or ""
    code = code.lower().split("-", 1)[0]
    return code if code in {"zh", "en", "ja"} else "zh"


async def _record_stat(database: Database, key: str) -> None:
    try:
        await database.incr_stat(key)
    except Exception:
        # Statistics are advisory and must not change an already committed
        # challenge outcome, but the failure remains visible to operators.
        log.exception("failed to record challenge statistic %s", key)


def _cancel_jobs(application: TelegramApplication, user_id: int) -> list[dict[str, Any]]:
    queue = application.job_queue
    if queue is None:
        return []
    data: list[dict[str, Any]] = []
    for job in queue.get_jobs_by_name(f"captcha:{user_id}"):
        if isinstance(job.data, dict):
            data.append(job.data)
        job.schedule_removal()
    return data


async def _edit_challenge_messages(
    application: TelegramApplication,
    jobs: list[dict[str, Any]],
    text: str,
) -> bool:
    edited = False
    for data in jobs:
        try:
            await application.bot.edit_message_text(
                chat_id=int(data["chat_id"]),
                message_id=int(data["message_id"]),
                text=text,
            )
            edited = True
        except (KeyError, TypeError, ValueError, TelegramError):
            continue
    return edited


async def _notify_success(
    application: TelegramApplication,
    user: User,
    settings: BotSettings,
) -> None:
    lang = _user_language(user)
    jobs = _cancel_jobs(application, user.user_id)
    edited = await _edit_challenge_messages(application, jobs, t("captcha.ok", lang))
    if not edited:
        try:
            await application.bot.send_message(user.user_id, t("captcha.ok", lang))
        except TelegramError:
            pass
    start = start_message_for(settings, lang)
    if not start:
        return
    try:
        await application.bot.send_message(
            user.user_id,
            start,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except TelegramError:
        try:
            await application.bot.send_message(user.user_id, start)
        except TelegramError:
            pass


async def _apply_failure_penalty(
    application: TelegramApplication,
    user: User,
    settings: BotSettings,
    current: int,
) -> None:
    database: Database = application.bot_data["db"]
    lang = _user_language(user)
    if settings.captcha_ban_on_fail:
        await database.set_flags(user.user_id, is_banned=True)
        message = t("captcha.fail_ban", lang)
    else:
        await database.set_flags(
            user.user_id,
            muted_until=current + max(60, settings.rate_limit_mute),
        )
        message = t("captcha.expired", lang)
    jobs = _cancel_jobs(application, user.user_id)
    if await _edit_challenge_messages(application, jobs, message):
        return
    try:
        await application.bot.send_message(user.user_id, message)
    except TelegramError:
        pass
