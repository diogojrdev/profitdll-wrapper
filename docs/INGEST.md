# Historical Data Ingestion

The `profitdll_wrapper.ingest` subpackage turns ProfitDLL's asynchronous
historical-data callbacks into a bounded, persistable extraction. It ships a
pluggable sink layer, an ingestion runner, and the `profitdll-ingest` CLI.

## Overview

```
ProfitDLL  --(callbacks)-->  ProfitClient  --(events)-->  ingest_history()  -->  DataSink
                              (HISTORICAL_TRADE,          (inactivity                (SQLite / CSV /
                               DAILY)                      watchdog)                  Parquet / Postgres)
```

ProfitDLL streams historical trades asynchronously via callbacks and never
emits an explicit "end of stream" signal — it simply stops calling the
handler. `ingest_history` turns that into a bounded operation by stopping the
client once no records arrive for `inactivity_timeout` seconds (with a hard
`max_timeout` ceiling).

## Backends

| Backend | Extra | Description |
|---|---|---|
| `sqlite` | — (stdlib) | Default. Single-file database, composite primary keys, UPSERT idempotency. |
| `csv` | — (stdlib) | Two append-mode files (`trades.csv`, `daily_candles.csv`). |
| `parquet` | `uv sync --extra parquet` | Columnar + compressed; one timestamped file per flush batch. |
| `postgres` | `uv sync --extra postgres` | PostgreSQL via psycopg3. TimescaleDB hypertable auto-created when available. |

### Optional extras

```bash
uv sync --extra postgres          # psycopg[binary]
uv sync --extra parquet           # duckdb
uv sync --extra all               # both
```

The library core remains dependency-free; optional backends are imported
lazily and raise an instructive `ImportError` if the extra is missing.

## CLI

```bash
profitdll-ingest \
    --ticker VALE3,PETR4 \
    --exchange B,B \
    --start 01/01/2026 --end 31/01/2026 \
    --to sqlite \
    --db-url sqlite:///./profit_data.db \
    --data-types trades,candles \
    --batch-size 500 \
    --inactivity-timeout 15 \
    --max-timeout 300
```

| Flag | Env var | Default | Description |
|---|---|---|---|
| `--ticker` | — | — | One or more comma-separated tickers (repeatable). |
| `--tickers-file` | — | — | File with one `TICKER [EXCHANGE]` per line. |
| `--exchange` | — | `B` | Exchange codes aligned with `--ticker` (`B` Bovespa, `F` BMF, …). |
| `--start` / `--end` | — | — | Interval bounds, `DD/MM/YYYY [HH:MM:SS]`. |
| `--to` | `SINK_BACKEND` | `sqlite` | Sink backend. |
| `--db-url` | `DATABASE_URL` | `sqlite:///./profit_data.db` | sqlite/postgres connection string. |
| `--output-dir` | `CSV_OUTPUT_DIR` | `./data` | csv/parquet output directory. |
| `--data-types` | — | `trades` | Subset of `trades,candles`. |
| `--batch-size` | `BATCH_SIZE` | `500` | Rows buffered before an automatic flush. |
| `--inactivity-timeout` | `INACTIVITY_TIMEOUT` | `15` | Seconds of silence before a ticker is assumed done. |
| `--max-timeout` | `MAX_TIMEOUT` | `300` | Hard upper bound for the whole run. |

Credentials are read from `.env` / the environment (see `.env.example`).

## Programmatic API

```python
from profitdll_wrapper import ProfitClient
from profitdll_wrapper.ingest import create_sink, ingest_history

sink = create_sink("sqlite", db_url="profit.db", batch_size=500)
with ProfitClient(...) as client:
    stats = ingest_history(
        client=client,
        sink=sink,
        tickers=[("VALE3", "B"), ("WDOFUT", "F")],
        start_date="01/01/2026 09:00:00",
        end_date="31/01/2026 18:00:00",
        data_types=["trades", "candles"],
        inactivity_timeout=15.0,
        max_timeout=300.0,
    )
sink.close()

for ts in stats.tickers:
    print(f"{ts.ticker}: {ts.trades_written} trades, {ts.candles_written} candles")
```

Since v0.4.0, completion is not guessed from silence alone: the DLL's vendor
progress callback (`TProgressCallback`, registered at initialization) is
exposed as `Event.HISTORY_PROGRESS` (`HistoryProgress(asset, progress)`), and
per the manual's `GetHistoryTrades` entry the progress runs 1→100 — **100
means the request finished**. Both runners treat `progress >= 100` (confirmed
by a short inactivity drain) as the real per-ticker completion signal, with
timeouts as fallbacks:

- **`first_event_timeout`** (default 60 s) — grace for the FIRST event (trade,
  candle or progress) of a ticker. A ticker that never receives anything is
  flagged `empty=True` with a `WARNING` log instead of being silently declared
  complete: a response still queued inside the DLL is not a finished stream.
- **`inactivity_timeout`** — silence after events started flowing (and the
  drain window applied after progress reaches 100).
- **`max_timeout`** / `request_timeout` — hard ceilings (whole run / per request).

Per-ticker results (`TickerStats`) now also report `completed_by_progress`,
`empty`, `timed_out`, `discarded_out_of_window` and `discarded_stray`, so
`trades_written == 0` is distinguishable from "the request never drained".

### Multi-window runs (`ingest_windows`)

`ingest_history` is **one window per run** by contract: every ticker shares
`start_date`/`end_date` and all requests are fired up front. That is safe
because every late answer still falls inside the same window. Stacking runs
with *different* windows on one session is not: the historical-trade event
carries no window attribution, so late DLL responses leak between groups (a
real production incident recorded one day's tape with another day's trades).

Use `ingest_windows` for per-ticker windows — one request in flight at a
time, completion by progress, and contamination defenses:

```python
from profitdll_wrapper.ingest import ingest_windows

with ProfitClient(...) as client:
    stats = ingest_windows(
        client=client,
        sink=sink,
        tickers=[
            # (ticker, exchange, start, end) — execution order, duplicates allowed
            ("PETR4", "B", "27/08/2026 10:00:00", "27/08/2026 16:55:00"),
            ("VALE3", "B", "27/08/2026 10:00:00", "27/08/2026 16:55:00"),
            ("PETR4", "B", "02/09/2026 10:00:00", "02/09/2026 16:55:00"),
        ],
        first_event_timeout=60.0,   # nothing received at all -> empty + warning
        inactivity_timeout=15.0,    # also the drain after progress hits 100
        request_timeout=300.0,      # hard ceiling per request
        max_timeout=1800.0,         # hard ceiling for the whole run
        stop_client=False,          # keep the session for the next run
    )
```

Guarantees:

- The next request is only issued after the current one completes, so every
  answer is attributable to its request.
- Trades of the current ticker **outside its window** are discarded and
  counted in `TickerStats.discarded_out_of_window`; trades of **another
  ticker** (late answers of previous requests) are discarded and counted in
  `discarded_stray`. Nothing outside a request's window reaches the sink.
- Trades-only (daily candles have no per-window semantics; use
  `ingest_history` with `data_types=["candles"]`).
- Timeouts never raise; inspect `timed_out`/`empty`/`invalid` per request.
  When `max_timeout` is exceeded, remaining requests are skipped and marked
  `timed_out`.

Both runners accept **`stop_client=False`** to keep the session open for the
next run on the same client (`ProfitClient.interrupt_run()` unblocks `run()`
without stopping event delivery), and they remove their event handlers when
they finish (`client.off`), so back-to-back runs never duplicate writes.

### Timezones (B3 → UTC)

The DLL reports naive B3-local timestamps. Sinks (and `create_sink`) accept
`assume_b3_local=True` to persist timezone-aware UTC instead — no
per-consumer `UtcSink` subclass needed:

```python
sink = create_sink("postgres", db_url=..., assume_b3_local=True)
```

The standalone helper `b3_local_to_utc(dt)` (exported from the package root)
converts single datetimes. It uses `zoneinfo`'s `America/Sao_Paulo` when the
IANA database is available and falls back to the fixed UTC-03:00 offset
otherwise (exact for every date since Brazil abolished DST in 2019 — and the
server caps history at 30 days anyway).

### Reusing a Postgres connection

`PostgresSink` accepts an existing psycopg3 connection instead of a URL —
handy for one-connection-per-process across multi-group runs. Borrowed
connections are never closed by the sink:

```python
conn = psycopg.connect(db_url)
sink_a = PostgresSink(connection=conn)
sink_b = PostgresSink(connection=conn)   # shared
...
conn.close()                              # caller owns the lifecycle
```

## Schema

Both tables use composite primary keys so re-running an extraction is safe
(rows are upserted, never duplicated).

### `trades`

| Column | Type | Notes |
|---|---|---|
| `ticker` | TEXT | PK |
| `exchange` | TEXT | PK |
| `trade_number` | BIGINT/INTEGER | PK |
| `price` | DOUBLE PRECISION/REAL | |
| `quantity` | BIGINT/INTEGER | |
| `volume` | DOUBLE PRECISION/REAL | |
| `buy_agent` | INTEGER | |
| `sell_agent` | INTEGER | |
| `trade_type` | SMALLINT/INTEGER | aggressor code |
| `timestamp` | TEXT | ISO-8601 datetime |
| `is_edit` | BOOLEAN/INTEGER | correction flag |

Index: `(ticker, timestamp)`.

### `daily_candles`

| Column | Type |
|---|---|
| `ticker`, `exchange` (PK) | TEXT |
| `date` (PK) | TEXT (`DD/MM/YYYY HH:mm:SS.ZZZ`) |
| `open`, `high`, `low`, `close`, `volume`, `adjustment`, `max_limit`, `min_limit` | DOUBLE PRECISION/REAL |
| `volume_buyer`, `volume_seller` | DOUBLE PRECISION/REAL |
| `quantity`, `trades`, `open_interest` | BIGINT/INTEGER |
| `quantity_buyer`, `quantity_seller`, `trades_buyer`, `trades_seller` | BIGINT/INTEGER |

Index: `(ticker, date)`.

## TimescaleDB (hypertables)

When the `postgres` backend detects the `timescaledb` extension, the `trades`
table is converted to a hypertable partitioned by `timestamp`. This enables
efficient time-range queries, native compression, and retention policies. On
plain PostgreSQL the table behaves as a normal table with the same indexes.

## Idempotency

All sinks UPSERT on the composite primary key:

- **trades**: `(ticker, exchange, trade_number)`
- **daily_candles**: `(ticker, exchange, date)`

Re-running the same extraction (or overlapping intervals) updates existing
rows rather than duplicating them. This makes backfills and retries safe.

## Tuning

- **`batch_size`**: Larger batches reduce I/O round-trips but increase peak
  memory. `500`–`2000` is a sensible range for tick data.
- **`inactivity_timeout`**: Lower values make the run end faster when a
  ticker has little data; raise it for very liquid instruments that stream in
  bursts. Since v0.4.0 this is only the fallback/drain heuristic — the
  progress callback (100) is the real completion signal.
- **`max_timeout`**: Always set a hard ceiling for unattended runs.

## Known limits

### `HISTORY_PERIOD_LIMIT` (30-day server cap)

The Nelogica API rejects historical requests whose start date is older than
**30 days** relative to the current server date, returning
`HistoryPeriodLimitError` (subclass of `InvalidArgumentError`, since v0.4.0):
*"ProfitDLL error HISTORY_PERIOD_LIMIT (0x8000002e) — the server rejects
requests whose start date is older than 30 days; split the range into
<=30-day windows."*

To backfill older data, split the range into ≤30-day windows and run the CLI
once per window. Re-runs are idempotent (UPSERT), so overlapping windows are
safe.

```bash
# Backfill 3 months in <=30-day windows:
profitdll-ingest --ticker PETR4 --start 12/07/2026 --end 10/08/2026   # window 1
profitdll-ingest --ticker PETR4 --start 12/06/2026 --end 11/07/2026   # window 2
profitdll-ingest --ticker PETR4 --start 13/05/2026 --end 12/06/2026   # window 3
```

### TimescaleDB default credentials

`docker compose up` starts TimescaleDB with these defaults (override via `.env`):

| Variable | Default |
|---|---|
| `TIMESCALE_USER` | `profit` |
| `TIMESCALE_PASSWORD` | `changeme` |
| `TIMESCALE_DB` | `profit` |
| `TIMESCALE_PORT` | `5432` |

The default password is a placeholder — change it in `.env` before real use.
If the cluster was already initialized with `changeme`, either recreate the
volume or change the password in place:

```bash
# Option A: recreate from scratch (loses data)
docker compose down -v && docker compose up -d timescaledb

# Option B: change the password keeping data
docker exec -it profitdll-timescaledb psql -U profit -d profit \
    -c "ALTER USER profit PASSWORD '<new_password>';"
```

## Notes

- **Completion signal**: since v0.4.0 the vendor progress callback
  (`TProgressCallback`) drives per-ticker completion (`progress >= 100` plus a
  short drain); the inactivity/first-event timeouts remain as fallbacks for
  requests the DLL never answers.
- **Multi-ticker (`ingest_history`)**: tickers are requested up front and
  consumed concurrently; the run completes when *every* requested ticker
  finished (progress/idle/first-event) or `max_timeout` is reached. One
  window per run — see [Multi-window runs](#multi-window-runs-ingest_windows).
- **Single DLL lifecycle per process**: after `disconnect()` (which calls
  `DLLFinalize`), constructing a new `ProfitClient` in the same process
  raises `RuntimeError` immediately — the native DLL does not support
  re-initialization. Use one subprocess per session for sequential sessions.
- **Invalid tickers**: `Event.INVALID_TICKER` is handled gracefully — the
  ticker is flagged and skipped without aborting the run.
