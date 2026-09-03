"""Timezone helpers for B3 (Bovespa/BMF) market data.

The DLL reports naive local timestamps ("DD/MM/YYYY HH:MM:SS.mmm") in the
exchange's timezone — America/Sao_Paulo for both B3 exchanges ("B" and "F").
These helpers centralize the naive-B3-to-UTC conversion so consumers don't
each reimplement their own ``UtcPostgresSink``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

# Fallback for environments without the IANA tz database (notably Windows
# without the ``tzdata`` package — the wrapper keeps zero runtime deps).
# Brazil abolished DST in 2019, so the fixed UTC-03:00 offset is exact for
# every date since; historical requests are capped at 30 days by the server,
# so post-2019 is the only reachable range in practice.
_B3_FALLBACK_TZ = timezone(-timedelta(hours=3), "B3")


def _load_b3_tz() -> tzinfo:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover - zoneinfo is stdlib on supported Pythons
        return _B3_FALLBACK_TZ
    try:
        return ZoneInfo("America/Sao_Paulo")
    except Exception:  # pragma: no cover - depends on the tz database being present
        return _B3_FALLBACK_TZ


B3_TZ: tzinfo = _load_b3_tz()


def b3_local_to_utc(value: datetime) -> datetime:
    """Normalizes a trade/candle timestamp to timezone-aware UTC.

    Naive datetimes are assumed to be B3 local time (America/Sao_Paulo), which
    is what the DLL delivers; aware datetimes are converted from their own
    zone.

    Args:
        value: Naive B3-local or aware datetime.

    Returns:
        The equivalent moment as an aware UTC datetime.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=B3_TZ)
    return value.astimezone(timezone.utc)


__all__ = ["B3_TZ", "b3_local_to_utc"]
