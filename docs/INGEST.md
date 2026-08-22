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
  bursts. The DLL does not signal completion, so this is a heuristic.
- **`max_timeout`**: Always set a hard ceiling for unattended runs.

## Known limits

### `HISTORY_PERIOD_LIMIT` (30-day server cap)

The Nelogica API rejects historical requests whose start date is older than
**30 days** relative to the current server date, returning
`InvalidArgumentError: ProfitDLL error HISTORY_PERIOD_LIMIT (0x8000002e)`.

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

- **No completion signal**: The native DLL does not emit an explicit
  end-of-history event. The runner relies on the inactivity heuristic above.
- **Multi-ticker**: Tickers are requested up front and consumed concurrently;
  the inactivity watchdog considers the run complete only when *every*
  requested ticker has gone quiet (or `max_timeout` is reached).
- **Invalid tickers**: `Event.INVALID_TICKER` is handled gracefully — the
  ticker is flagged and skipped without aborting the run.
