from __future__ import annotations

from datetime import datetime, timezone

import pytest

from thomas.autonomy.scheduler import compute_next_run as compute_compat_next_run
from thomas.core.timezones import resolve_timezone
from thomas.marketplace.autonomy.scheduler import compute_next_run as compute_marketplace_next_run


def test_resolve_timezone_uses_dst_aware_iana_data_on_windows() -> None:
    chicago = resolve_timezone("America/Chicago")

    assert datetime(2026, 1, 15, tzinfo=chicago).utcoffset().total_seconds() == -6 * 60 * 60
    assert datetime(2026, 7, 15, tzinfo=chicago).utcoffset().total_seconds() == -5 * 60 * 60


@pytest.mark.parametrize("name", ["../secret", "C:/Windows/System32", "America//Chicago", "America/../../secret"])
def test_resolve_timezone_rejects_paths_and_malformed_names(name: str) -> None:
    with pytest.raises(ValueError, match="invalid timezone"):
        resolve_timezone(name)


def test_both_schedulers_accept_work_week_schedule_without_system_tzdata() -> None:
    schedule = {"type": "weekly", "at": "09:00", "tz": "America/Chicago", "dow": [0, 1, 2, 3, 4]}
    now = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)  # Thursday, after 09:00 local.

    assert compute_compat_next_run(schedule, now) == datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)
    assert compute_marketplace_next_run(schedule, now) == datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)
