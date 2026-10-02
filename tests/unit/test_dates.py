from datetime import UTC, date, datetime

import pytest

from app.utils import dates
from app.utils.dates import today_in_business_timezone


@pytest.mark.parametrize(
    ("utc_now", "expected"),
    [
        (datetime(2026, 9, 18, 21, 59, tzinfo=UTC), date(2026, 9, 18)),
        (datetime(2026, 9, 18, 22, 0, tzinfo=UTC), date(2026, 9, 19)),
        (datetime(2026, 1, 15, 23, 0, tzinfo=UTC), date(2026, 1, 16)),
    ],
    ids=["before_local_midnight_summer", "after_local_midnight_summer", "after_local_midnight_winter"],
)
def test_today_in_business_timezone_utc_clock_returns_the_warsaw_date(monkeypatch, utc_now, expected):
    # Arrange: a UTC server must not report yesterday after midnight in the business timezone
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_now.astimezone(tz)

    monkeypatch.setattr(dates, "datetime", FixedDatetime)

    # Act
    today = today_in_business_timezone()

    # Assert
    assert today == expected
