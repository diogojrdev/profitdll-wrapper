"""Integration tests for v0.4.0 fixes against the real DLL.

Runs in a DEDICATED SUBPROCESS (the same pattern the tape synchronizer uses):
the native DLL supports a single init/finalize cycle per process, so both
verifications below share one subprocess lifecycle —

1. Multi-window repro (DoD 1): same tickers, two different windows, one
   session via ``ingest_windows``; each result must contain only trades of
   its own window and each request must complete via progress == 100, even
   with the DLL delaying answers.
2. Second lifecycle (DoD 2): after ``disconnect()``, constructing a new
   ProfitClient in the same process must fail fast (<1s) with the clear
   single-lifecycle RuntimeError instead of the old 30s connection timeout.

Skips unless Windows + resolvable DLL + ACTIVATION_KEY/USER/PASSWORD in .env.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from tests.integration.conftest import require_dll_and_credentials

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The child process does the whole flow and reports back on stdout as a single
# JSON line; credentials travel via environment variables only.
_CHILD_SCRIPT = r'''
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from profitdll_wrapper import ProfitClient
from profitdll_wrapper._bindings.errors import AuthError, ProfitConnectionError
from profitdll_wrapper.ingest import ingest_windows
from profitdll_wrapper.ingest.sqlite_sink import SqliteSink

DB = Path(sys.argv[1])


def recent_trading_days(n):
    """Most recent `n` distinct weekdays strictly before today (B3 calendar
    approximation; holidays simply yield zero-trade windows)."""
    days = []
    d = date.today()
    while len(days) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    return list(reversed(days))


def main():
    key = os.environ["ACTIVATION_KEY"]
    user = os.environ["USER"]
    password = os.environ["PASSWORD"]

    day_a, day_b = recent_trading_days(2)
    windows = []
    for day in (day_b, day_a):  # chronological order, like the synchronizer
        start = day.strftime("%d/%m/%Y") + " 10:00:00"
        end = day.strftime("%d/%m/%Y") + " 16:55:00"
        for ticker in ("PETR4", "VALE3"):
            windows.append((ticker, "B", start, end))

    client = ProfitClient(
        activation_key=key, user=user, password=password, mode="market_data"
    )
    sink = SqliteSink(db_url=str(DB), batch_size=500)
    result = {
        "day_a": day_a.isoformat(),
        "day_b": day_b.isoformat(),
        "windows": [],
        "db_rows": [],
    }
    try:
        try:
            client.connect(timeout=30.0)
        except (ProfitConnectionError, AuthError) as exc:
            result["skipped"] = f"live infra unavailable: {exc}"
            print(json.dumps(result))
            return

        stats = ingest_windows(
            client=client,
            sink=sink,
            tickers=windows,
            first_event_timeout=60.0,
            inactivity_timeout=15.0,
            request_timeout=300.0,
            max_timeout=1200.0,
        )
        result["elapsed"] = stats.elapsed_seconds
        for ts in stats.tickers:
            result["windows"].append(
                {
                    "ticker": ts.ticker,
                    "trades": ts.trades_written,
                    "completed_by_progress": ts.completed_by_progress,
                    "empty": ts.empty,
                    "timed_out": ts.timed_out,
                    "invalid": ts.invalid,
                    "discarded_out_of_window": ts.discarded_out_of_window,
                    "discarded_stray": ts.discarded_stray,
                }
            )
    finally:
        sink.close()
        client.disconnect()

    # DoD 2: second lifecycle in the same process must fail FAST with the
    # clear message (not the 30s connection timeout).
    started = time.perf_counter()
    try:
        ProfitClient(
            activation_key=key, user=user, password=password, mode="market_data"
        )
    except RuntimeError as exc:
        result["second_lifecycle"] = {
            "raised": True,
            "message": str(exc),
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
    else:
        result["second_lifecycle"] = {"raised": False}

    print(json.dumps(result))


main()
'''


def _env_for_child(simulator_env: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("ACTIVATION_KEY", "USER", "PASSWORD", "PROFITDLL_PATH"):
        if simulator_env.get(key):
            env[key] = simulator_env[key]
    return env


@pytest.mark.integration
class TestRealDLLWindowsAndLifecycle:
    def test_multi_window_purity_and_second_lifecycle(
        self, simulator_env: dict[str, str], tmp_path: Path
    ) -> None:
        require_dll_and_credentials(simulator_env)

        db = tmp_path / "windows.db"
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD_SCRIPT, str(db)],
            capture_output=True,
            text=True,
            timeout=1500,
            cwd=_REPO_ROOT,
            env=_env_for_child(simulator_env),
        )
        assert proc.returncode == 0, f"child failed:\n{proc.stderr[-4000:]}"

        lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
        assert lines, f"child printed no JSON result:\n{proc.stderr[-2000:]}"
        data = json.loads(lines[-1])

        if "skipped" in data:
            pytest.skip(data["skipped"])

        day_b, day_a = data["day_b"], data["day_a"]
        assert len(data["windows"]) == 4

        # DoD 1: every request completes via progress == 100 (real completion
        # signal from the DLL's TProgressCallback), no silent losses.
        for w in data["windows"]:
            assert w["completed_by_progress"] is True, w
            assert w["empty"] is False and w["timed_out"] is False and w["invalid"] is False, w

        # DoD 1: window purity — every tape only contains trades of its own
        # date (validate against the SQLite sink written by the child).
        import sqlite3

        conn = sqlite3.connect(db)
        try:
            rows = conn.execute('SELECT ticker, timestamp FROM "trades"').fetchall()
        finally:
            conn.close()
        assert rows, "expected at least one trade from two full-session windows"
        by_window_date = {day_b: 0, day_a: 0}
        for ticker, ts in rows:
            day = datetime.fromisoformat(ts).date().isoformat()
            assert day in by_window_date, f"trade of {ticker} outside both windows: {ts}"
            by_window_date[day] += 1
        assert by_window_date[day_b] > 0, "window B (older day) recorded no trades"
        assert by_window_date[day_a] > 0, "window A (newer day) recorded no trades"

        # DoD 2: second lifecycle fails fast with the clear message.
        second = data["second_lifecycle"]
        assert second["raised"] is True, "second ProfitClient should have raised"
        assert "único ciclo de vida" in second["message"]
        assert second["elapsed_s"] < 1.0, second
