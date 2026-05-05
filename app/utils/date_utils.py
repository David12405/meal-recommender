from __future__ import annotations

from datetime import datetime, timedelta


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def days_between(later: datetime, earlier: datetime) -> int:
    """Signed day difference: `later - earlier` in whole days (floor)."""
    delta = later - earlier
    return delta.days
