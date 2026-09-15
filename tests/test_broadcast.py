from datetime import timedelta

from app.services.broadcast import retry_after_seconds


def test_retry_after_supports_ptb_time_period_types() -> None:
    assert retry_after_seconds(3) == 3.0
    assert retry_after_seconds(timedelta(seconds=2.5)) == 2.5
