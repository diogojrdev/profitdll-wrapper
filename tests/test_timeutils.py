"""Testes dos helpers de timezone B3 (b3_local_to_utc / assume_b3_local)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from profitdll_wrapper import AssetId, Trade, b3_local_to_utc
from profitdll_wrapper.ingest.sqlite_sink import SqliteSink


def _trade(ts: datetime) -> Trade:
    return Trade(
        asset=AssetId(ticker="PETR4", exchange="B"),
        trade_number=1,
        price=10.0,
        quantity=100,
        volume=1000.0,
        buy_agent=1,
        sell_agent=2,
        trade_type=2,
        timestamp=ts,
        is_edit=False,
    )


def test_b3_local_to_utc_naive() -> None:
    # B3 (America/Sao_Paulo) é UTC-3 desde o fim do DST (2019).
    result = b3_local_to_utc(datetime(2026, 9, 2, 10, 0, 0))
    assert result == datetime(2026, 9, 2, 13, 0, 0, tzinfo=timezone.utc)
    assert result.tzinfo is timezone.utc


def test_b3_local_to_utc_aware_passthrough() -> None:
    aware = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
    assert b3_local_to_utc(aware) == aware


def test_b3_local_to_utc_aware_other_zone() -> None:
    from datetime import timedelta

    ny = timezone(-timedelta(hours=4))
    result = b3_local_to_utc(datetime(2026, 9, 2, 10, 0, 0, tzinfo=ny))
    assert result == datetime(2026, 9, 2, 14, 0, 0, tzinfo=timezone.utc)


def test_sink_assume_b3_local_converts_timestamps(tmp_path: Path) -> None:
    db = tmp_path / "utc.db"
    sink = SqliteSink(db_url=str(db), batch_size=10, assume_b3_local=True)
    sink.write_trade(_trade(datetime(2026, 9, 2, 10, 0, 0)))
    sink.close()

    conn = sqlite3.connect(db)
    try:
        ts = conn.execute('SELECT timestamp FROM "trades"').fetchone()[0]
    finally:
        conn.close()
    assert ts == "2026-09-02T13:00:00+00:00"


def test_sink_default_keeps_naive_timestamps(tmp_path: Path) -> None:
    db = tmp_path / "naive.db"
    sink = SqliteSink(db_url=str(db), batch_size=10)
    sink.write_trade(_trade(datetime(2026, 9, 2, 10, 0, 0)))
    sink.close()

    conn = sqlite3.connect(db)
    try:
        ts = conn.execute('SELECT timestamp FROM "trades"').fetchone()[0]
    finally:
        conn.close()
    assert ts == "2026-09-02T10:00:00"
