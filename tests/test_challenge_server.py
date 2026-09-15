from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import ANY, AsyncMock

import httpx
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application as TornadoApplication

from app.challenge_server import VerifyHandler
from app.models import BotSettings, User
from app.services.turnstile import TURNSTILE_ACTION

CHALLENGE = "ts_" + "a" * 43


class ChallengeHandlerTest(AsyncHTTPTestCase):
    def setUp(self) -> None:
        async def worker(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "hostname": "challenge.example.com",
                    "action": TURNSTILE_ACTION,
                    "cdata": CHALLENGE,
                    "error-codes": [],
                },
            )

        self.database = SimpleNamespace(
            get_turnstile_challenge=AsyncMock(return_value=("active", 42, 0)),
            get_user=AsyncMock(
                return_value=User(
                    user_id=42,
                    username="alice",
                    first_name="Alice",
                    last_name=None,
                    language_code="en",
                )
            ),
            apply_turnstile_attempt=AsyncMock(return_value=("passed", 42, 0)),
            incr_stat=AsyncMock(),
            delete_captcha=AsyncMock(),
            set_flags=AsyncMock(),
        )
        self.worker_client = httpx.AsyncClient(transport=httpx.MockTransport(worker))
        self.bot = SimpleNamespace(
            send_message=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        telegram_application = SimpleNamespace(
            bot=self.bot,
            bot_data={
                "db": self.database,
                "settings_svc": SimpleNamespace(current=BotSettings()),
            },
            job_queue=None,
        )
        self.service = SimpleNamespace(
            sitekey="public-sitekey",
            database=self.database,
            client=self.worker_client,
            verify_url="https://worker.example/",
            expected_hostname="challenge.example.com",
            application=telegram_application,
        )
        super().setUp()

    def tearDown(self) -> None:
        self.io_loop.run_sync(self.worker_client.aclose)
        super().tearDown()

    def get_app(self) -> TornadoApplication:
        return TornadoApplication(
            [(r"/verify", VerifyHandler, {"service": self.service})]
        )

    def test_get_bootstraps_from_fragment_without_receiving_it(self) -> None:
        response = self.fetch(f"/verify#{CHALLENGE}")
        body = response.body.decode()
        assert response.code == 200
        assert CHALLENGE not in body
        assert 'data-action="turnstile-spin-v1"' in body
        assert "https://challenges.cloudflare.com" in response.headers[
            "Content-Security-Policy"
        ]
        assert response.headers["Cache-Control"].startswith("no-store")

    def test_valid_worker_result_atomically_completes_challenge(self) -> None:
        response = self.fetch(
            "/verify",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode(
                {
                    "challenge": CHALLENGE,
                    "cf-turnstile-response": "browser-token",
                }
            ),
        )
        assert response.code == 200
        assert "Verified" in response.body.decode()
        self.database.apply_turnstile_attempt.assert_awaited_once_with(
            CHALLENGE,
            ANY,
            True,
            3,
        )
        assert isinstance(self.database.apply_turnstile_attempt.await_args.args[1], int)
        self.database.incr_stat.assert_awaited_once_with("captcha_pass")

    def test_committed_success_survives_noncritical_followup_failures(self) -> None:
        self.database.incr_stat.side_effect = RuntimeError("statistics unavailable")
        self.bot.send_message.side_effect = RuntimeError("notification unavailable")
        response = self.fetch(
            "/verify",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode(
                {
                    "challenge": CHALLENGE,
                    "cf-turnstile-response": "browser-token",
                }
            ),
        )
        assert response.code == 200
        assert "Verified" in response.body.decode()

    def test_parameter_pollution_is_rejected_before_siteverify(self) -> None:
        response = self.fetch(
            "/verify",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=(
                f"challenge={CHALLENGE}&challenge={CHALLENGE}"
                "&cf-turnstile-response=browser-token"
            ),
        )
        assert response.code == 400
        self.database.get_turnstile_challenge.assert_not_awaited()
