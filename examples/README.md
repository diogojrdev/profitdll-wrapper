# Practical Examples & Cookbooks for `profitdll-wrapper`

This directory contains quick-reference guides and ready-to-run Python scripts demonstrating how to use `profitdll-wrapper` in real-world scenarios — from real-time market data streaming to automated trading bots and infrastructure monitoring.

---

## Example Directory Overview

| Script | Category | Description | Required Mode |
| :--- | :--- | :--- | :--- |
| [`01_subscribe_ticker.py`](01_subscribe_ticker.py) | **MVP / Quotes** | Minimal example to connect and receive real-time trade ticks. | `market_data` |
| [`02_price_depth.py`](02_price_depth.py) | **Price Book** | Positional order book depth monitoring and price level reading. | `market_data` |
| [`03_live_smoke.py`](03_live_smoke.py) | **Smoke Test** | Full validation of connections, callbacks, and queries against native DLL. | `market_data` / `routing` |
| [`04_send_order.py`](04_send_order.py) | **Routing** | Submitting limit buy/sell orders and tracking executions. | `routing` |
| [`05_market_data_streamer.py`](05_market_data_streamer.py) | **Data Streamer** | Collecting trades, V2 books, closing prices, and streaming to CSV / pandas DataFrame. | `market_data` |
| [`06_trading_bot_sample.py`](06_trading_bot_sample.py) | **Trading Bot** | Complete automated trading bot blueprint with state machine, order manager, Stop Loss & Take Profit. | `routing` |
| [`07_watchdog_and_reconciliation.py`](07_watchdog_and_reconciliation.py) | **Infra / Reconciliation** | DLL process health monitoring (`get_health_status`), auto-reconnection, and daily position reconciliation. | `routing` |
| [`08_corporate_actions_and_history.py`](08_corporate_actions_and_history.py) | **History & Adjustments** | Tick-by-tick trade history download (`get_history_trades`) and corporate actions (`subscribe_adjust_history`). | `market_data` |
| [`09_historical_to_database.py`](09_historical_to_database.py) | **History → Database** | Persisting historical trades to a SQLite database via the `ingest` subpackage (programmatic API behind the `profitdll-ingest` CLI). | `market_data` |
| [`10_times_and_trades_tui.py`](10_times_and_trades_tui.py) | **TUI / Market Data** | Rich Times & Trades with a native-style summary bar (Last/Change/High/Low/Open/Close/Bid), mirrored buyer → seller tape with aggressor-side highlighting, quantity bars and a buy/sell aggression pressure gauge. `--demo` runs anywhere without the DLL. | `market_data` |
| [`11_order_book_tui.py`](11_order_book_tui.py) | **TUI / Market Data** | Rich full Level-2 DOM: native-style summary bar, mirrored bid/ask sides (Time \| Broker \| Qty \| Price), spread (R$ / bps), proportional quantity bars and side totals. `--demo` runs anywhere without the DLL. | `market_data` |

---

## How to Run

### 1. Configure Credentials (`.env`)
Create or edit the `.env` file in project root with your ProfitDLL credentials:

```env
PROFITDLL_ACTIVATION_KEY=your_activation_key
PROFITDLL_USER=your_user
PROFITDLL_PASSWORD=your_password
PROFITDLL_ACCOUNT=your_trading_account
```

### 2. Execute an Example
Run any script using the `uv` package runner:

```bash
# Example 05: Data collector and CSV/DataFrame exporter
uv run python examples/05_market_data_streamer.py

# Example 06: Trading Bot (Full blueprint template)
uv run python examples/06_trading_bot_sample.py

# Example 07: DLL health watchdog and position reconciliation
uv run python examples/07_watchdog_and_reconciliation.py

# Example 08: Tick-by-tick historical trade download and corporate actions
uv run python examples/08_corporate_actions_and_history.py

# Example 09: Historical trades to a SQLite database
uv run python examples/09_historical_to_database.py

# Example 10: Times & Trades TUI (requires the 'tui' extra; --demo works on any OS)
uv run --extra tui python examples/10_times_and_trades_tui.py --demo

# Example 11: Full order book (DOM) TUI (requires the 'tui' extra; --demo works on any OS)
uv run --extra tui python examples/11_order_book_tui.py --demo
```

> **Note**: Examples 10 and 11 render with [`rich`](https://rich.readthedocs.io/) — install it
> with `uv sync --extra tui` (or pass `--extra tui` to `uv run`). Their `--demo` / `--mock`
> flag drives a synthetic feed, so no ProfitDLL binary, credentials, or Windows OS is needed.

> **Note**: Even outside market hours, examples execute safely, reading closing prices, asset info, and awaiting events without throwing unexpected errors.

