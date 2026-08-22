<div align="center">

# profitdll-wrapper

High-performance, idiomatic, typed, and memory-safe Python wrapper for **ProfitDLL** (Nelogica's native API).

[![PyPI](https://img.shields.io/pypi/v/profitdll-wrapper.svg?cacheSeconds=3600)](https://pypi.org/project/profitdll-wrapper)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue.svg)](https://www.python.org)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://docs.astral.sh/ruff)
[![Type Checking: mypy](https://img.shields.io/badge/mypy-strict-blue.svg)](https://mypy.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-v0.1.0--alpha-orange.svg)](#status)

</div>

---

> [!NOTE]
> **Status: v0.1.0 (alpha) — first public release. P0 (Trades), P1 (Price Depth) & P2 (Order Routing & Custody) validated against the vendor simulator.**
> Full test suite with 225 unit and ABI contract tests (80%+ code coverage), running under `mypy --strict`, `ruff`, and `pytest`. *Pure Enqueue* architecture immune to C ↔ GIL reentrancy crashes.

---

> [!WARNING]
> **Unofficial project — not affiliated with Nelogica.** `profitdll-wrapper` is an
> independent, community-driven wrapper. Profit, ProfitDLL, and related names are
> products and trademarks of Nelogica, which does not endorse, sponsor, or support
> this project. The proprietary DLL is not distributed here.
>
> **No financial responsibility.** This software can place real orders with real
> money when connected to a real brokerage account. It is provided "as is", without
> warranty of any kind, for research and educational purposes. The authors accept
> **no liability for financial losses, missed or duplicated orders, incorrect or
> delayed data, or any trading outcome**. Validate everything on a simulator/demo
> account first — you are solely responsible for the orders your code sends.

---

## What is `profitdll-wrapper`

`profitdll-wrapper` is a modern Python wrapper for Nelogica's ProfitDLL — a native C/Pascal API (`stdcall` calling convention, featuring raw memory pointers and callback threads on a dedicated C `ConnectorThread`).

It abstracts away low-level ctypes complexity and provides:
- **Idiomatic API**: Context managers (`with`), immutable dataclasses (`Trade`, `PriceLevel`, `PriceBookSnapshot`, `DailyCandle`, `Order`, `Position`, `Account`), strict `enum` types, and comprehensive type hints;
- **Order Routing & Custody**: Limit orders (`send_buy_order`, `send_sell_order`), market orders (`send_market_buy`, `send_market_sell`), order cancellations (`cancel_order`, `cancel_all_orders`), and real-time custody position tracking (`get_position`, `Event.ORDER`, `Event.POSITION`);
- **Pure Enqueue Architecture**: C callbacks only enqueue lightweight positional payloads in microseconds without reentrant ctypes calls, preventing deadlocks and segfaults under high market volume;
- **Fault Tolerance & Safety**: User exception isolation in event handlers ensures callback failures never crash the native DLL process or interrupt data streams;
- **Zero Runtime Dependencies**: Built strictly using the Python standard library (`dependencies = []`).

Detailed architectural and API documentation is available in [`docs/`](docs/):

| Document | Content |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layer design, abstraction patterns, and thread-safety invariants |
| [`docs/API_SURFACE.md`](docs/API_SURFACE.md) | Native ProfitDLL function mapping and ABI audit |
| [`docs/INGEST.md`](docs/INGEST.md) | Historical data ingestion: sinks, schema, and the `profitdll-ingest` CLI |

---

## Installation

Install from [PyPI](https://pypi.org/project/profitdll-wrapper) with pip:

```bash
pip install profitdll-wrapper
```

Or, in a project managed with [uv](https://docs.astral.sh/uv):

```bash
uv add profitdll-wrapper
```

> [!TIP]
> The distribution name is `profitdll-wrapper` (hyphen), but the import name is
> `profitdll_wrapper` (underscore):
> ```python
> from profitdll_wrapper import Event, ProfitClient
> ```

**Requirements:** Python 3.10+ on **Windows** (the native ProfitDLL is a Windows `stdcall` library).

### Optional extras

The core package has zero runtime dependencies. Ingest backends are opt-in:

```bash
pip install "profitdll-wrapper[postgres]"   # PostgreSQL / TimescaleDB sink (psycopg)
pip install "profitdll-wrapper[parquet]"    # Parquet sink (duckdb)
pip install "profitdll-wrapper[all]"        # everything
```

### The Native (Proprietary) DLL

Nelogica's ProfitDLL is proprietary and **is not** bundled with this package.
To connect to Nelogica servers or simulator:
1. Set the environment variable `PROFITDLL_PATH=/path/to/ProfitDLL.dll` (or `ProfitDLL64.dll`), or;
2. Place the DLL inside a `dll/` directory in your working directory.
3. Create a `.env` file in your working directory with your simulator credentials:
   ```env
   ACTIVATION_KEY=your_key
   USER=your_username
   PASSWORD=your_password
   ```

The DLL directory must also contain the vendor runtime data (broker routing files); keep it out of version control.

---

## Quickstart

### 1. Real-Time Trade Ticks (P0)

```python
from profitdll_wrapper import Event, ProfitClient, Trade

with ProfitClient(
    activation_key="KEY...",
    user="USER...",
    password="PASSWORD...",
    mode="market_data",  # "market_data" or "routing"
    # broker_id=15003,   # optional; defaults to BROKER in the .env file
) as client:
    client.subscribe("WDOFUT", exchange="F")

    @client.on(Event.TRADE)
    def on_trade(trade: Trade) -> None:
        print(
            f"{trade.asset.ticker} | Price: {trade.price:.2f} x{trade.quantity} | Aggressor: {trade.trade_type}"
        )

    client.run()  # blocks keeping event loop active (Ctrl+C to exit)
```

### 2. Price Book / Price Depth & Thread-Safe Queries (P1)

```python
from profitdll_wrapper import Event, PriceLevel, ProfitClient

with ProfitClient(
    activation_key="KEY...",
    user="USER...",
    password="PASSWORD...",
    mode="market_data",
) as client:
    client.subscribe_price_depth("PETR4", exchange="B")

    @client.on(Event.PRICE_LEVEL)
    def on_level(level: PriceLevel) -> None:
        print(
            f"[{level.update_type.name}] {level.side.name} pos={level.position} qty={level.quantity}"
        )

    # Thread-safe level query outside of callback
    # top_buy = client.get_price_group("PETR4", side=0, position=0, exchange="B")

    client.run()
```

---

## Practical Examples

Explore the [`examples/`](examples/) directory:

- [`01_subscribe_ticker.py`](examples/01_subscribe_ticker.py): Minimal real-time trade tick streaming;
- [`02_price_depth.py`](examples/02_price_depth.py): Order book depth update and snapshot streaming;
- [`03_live_smoke.py`](examples/03_live_smoke.py): Complete self-contained live smoke test (connects, collects events, generates report).

---

## Historical Data → Database

The `profitdll-ingest` command downloads tick-by-tick historical trades (and optional daily candles) via ProfitDLL and persists them to a configurable backend. SQLite and CSV are built in (zero extra dependencies); Parquet and PostgreSQL/TimescaleDB ship as optional extras.

### Quickstart (SQLite, zero deps)

```bash
pip install profitdll-wrapper
profitdll-ingest --ticker VALE3 --start 01/01/2026 --end 31/01/2026
# -> writes to ./profit_data.db
```

### PostgreSQL / TimescaleDB via Docker

The database runs in Docker; the ingestion script runs on the Windows host (where the native DLL lives). Grab `docker-compose.yml` and `.env.example` from the repository.

```bash
cp .env.example .env             # set TIMESCALE_PASSWORD
docker compose up -d timescaledb
pip install "profitdll-wrapper[postgres]"
profitdll-ingest --ticker VALE3,PETR4 --exchange B,B \
    --start 01/01/2026 --end 31/01/2026 \
    --to postgres \
    --db-url postgresql://profit:secret@localhost:5432/profit
```

### Programmatic API

```python
from profitdll_wrapper import ProfitClient
from profitdll_wrapper.ingest import create_sink, ingest_history

sink = create_sink("sqlite", db_url="profit.db")
with ProfitClient(activation_key="...", user="...", password="...", mode="market_data") as client:
    stats = ingest_history(
        client=client,
        sink=sink,
        tickers=[("VALE3", "B")],
        start_date="01/01/2026 09:00:00",
        end_date="31/01/2026 18:00:00",
    )
print(f"{stats.trades_written} trades persisted in {stats.elapsed_seconds:.1f}s")
sink.close()
```

See [`docs/INGEST.md`](docs/INGEST.md) for schema details, hypertables, idempotency, and tuning, and [`examples/09_historical_to_database.py`](examples/09_historical_to_database.py) for a runnable end-to-end example.

---

## Development & Testing

This project uses [uv](https://docs.astral.sh/uv) for dependency management and tooling.

```bash
git clone https://github.com/diogojrdev/profitdll-wrapper.git
cd profitdll-wrapper
uv sync                                  # creates virtualenv and installs dev dependencies
uv run pytest                            # runs full test suite (225 unit & ABI tests)
uv run ruff check .                      # runs linter
uv run ruff format --check .               # checks code formatting
uv run mypy --strict src                 # checks strict type annotations
```

### Integration Testing with Real Native DLL

Integration tests running against Nelogica's real DLL and simulator use the `@pytest.mark.integration` marker:

```bash
uv run pytest -m integration
```

---

## License

[MIT](LICENSE). Nelogica's native ProfitDLL is proprietary software and is not included in this repository.

This is an **unofficial** project with no affiliation to Nelogica, and it is provided with **no financial liability** for trading losses — see the disclaimer at the top.

## Contributing

Contributions are welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development guidelines.

