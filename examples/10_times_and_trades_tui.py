"""Real-time Times & Trades TUI with buy/sell aggression analysis.

Replicates Nelogica Profit's classic "Times & Trades" window: a native-style
summary bar (Last, Change, Time, Volume, Trades, High, Low, Open, Close,
Bid), a buy/sell aggression pressure gauge, and a rolling tape of the last
trades — Time | Buyer | Price | Quantity | Seller | Aggressor — with
aggressor-side broker highlighting, proportional quantity bars and
block-trade flagging.

The summary bar's Bid comes from a price depth subscription
(`subscribe_price_depth`); session stats (High/Low/Open) are measured from
the first observed trade onwards (the wrapper exposes no daily OHLC query).

Thread model: ProfitDLL callbacks arrive on the wrapper's dispatcher thread;
handlers only mutate a lock-guarded state object, while the main thread owns
the `rich` rendering loop.

Prerequisites (live mode):
  * Windows 64-bit OS with Python 64-bit;
  * ProfitDLL binary available (defined via PROFITDLL_PATH env var or inside `dll/`);
  * Credentials set in `.env` file or environment variables.

Demo mode (`--demo`) needs none of the above: a synthetic feed fabricates
public `Trade` events and drives the exact same rendering pipeline, so the TUI
can be previewed on any OS.

Execution:

    uv run --extra tui python examples/10_times_and_trades_tui.py --demo
    uv run --extra tui python examples/10_times_and_trades_tui.py --ticker PETR4
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import (
    AssetId,
    BookSide,
    BookUpdateType,
    Event,
    PriceBookSnapshot,
    PriceLevel,
    ProfitClient,
    Trade,
)
from rich.box import SIMPLE
from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Subset of B3 broker/agent codes -> display names; unknown codes render as-is.
BROKER_NAMES: dict[int, str] = {
    3: "XP",
    8: "UBS",
    16: "JP Morgan",
    23: "Inter",
    40: "Goldman",
    72: "Bradesco",
    77: "Santander",
    85: "BTG",
    88: "Agora",
    107: "Terra",
    114: "Itau",
    120: "Genial",
    131: "Tullett",
}

# ProfitDLL trade type codes: who lifted the opposite side of the quote.
AGGRESSOR_BUYER = 2
AGGRESSOR_SELLER = 3

TAPE_SIZE = 30            # rolling buffer of rendered trades
BLOCK_TRADE_QTY = 10_000  # quantity above which a trade is highlighted as a block
DEMO_PREV_CLOSE = 40.80   # synthetic previous close used by --demo
GAUGE_WIDTH = 44          # pressure gauge width, in characters
QTY_BAR_WIDTH = 10        # fixed width of the quantity cell (background bar canvas)


def broker_name(agent_code: int) -> str:
    """Maps a B3 broker/agent code to a display name (raw code if unknown)."""
    return BROKER_NAMES.get(agent_code, str(agent_code))


def fmt_price(value: float) -> str:
    """Formats a price with pt-BR decimal comma (``41,25``)."""
    return f"{value:,.2f}".translate(str.maketrans(",.", ".,"))


def fmt_decimal(value: float, decimals: int = 2) -> str:
    """Formats a plain number with pt-BR decimal comma (``+1,10`` / ``7,3``)."""
    return f"{value:.{decimals}f}".replace(".", ",")


def fmt_qty(value: int) -> str:
    """Formats a quantity with pt-BR thousands separators (``5.000``)."""
    return f"{value:,}".replace(",", ".")


def fmt_time(moment: datetime) -> str:
    """Formats a timestamp as ``HH:MM:SS.mmm``."""
    return f"{moment:%H:%M:%S}.{moment.microsecond // 1000:03d}"


def fmt_volume_human(value: float) -> str:
    """Human-friendly financial volume (``19,97M``, ``842,10K``)."""
    if value >= 1_000_000:
        return fmt_decimal(value / 1_000_000) + "M"
    if value >= 1_000:
        return fmt_decimal(value / 1_000) + "K"
    return f"{value:.0f}"


@dataclass(frozen=True)
class TapeSnapshot:
    """Immutable view of the tape, consumed by the rendering thread."""

    trades: tuple[Trade, ...]
    last_price: float
    last_time: datetime | None
    prev_close: float | None
    total_volume: float
    trade_count: int
    block_count: int
    max_price: float | None
    min_price: float | None
    open_price: float | None
    best_bid: float | None
    buy_aggression: float
    sell_aggression: float


class TapeState:
    """Thread-safe rolling tape, session statistics and best-bid tracking.

    ``ingest`` / ``apply_book_snapshot`` / ``apply_bid_level`` run on the
    ProfitDLL dispatcher thread (live mode) or on the demo feed thread;
    ``snapshot`` runs on the main rendering thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._trades: deque[Trade] = deque(maxlen=TAPE_SIZE)
        self._last_price = 0.0
        self._last_time: datetime | None = None
        self._prev_close: float | None = None
        self._total_volume = 0.0
        self._trade_count = 0
        self._block_count = 0
        self._max_price: float | None = None
        self._min_price: float | None = None
        self._open_price: float | None = None
        self._bid_prices: list[float] = []  # position 0 = best bid (Of. Compra)
        self._buy_aggression = 0.0
        self._sell_aggression = 0.0

    def set_prev_close(self, close: float | None) -> None:
        with self._lock:
            self._prev_close = close if close and close > 0 else None

    def ingest(self, trade: Trade) -> None:
        with self._lock:
            self._trades.append(trade)
            if trade.is_edit:
                return  # corrections show on the tape only
            self._last_price = trade.price
            self._last_time = trade.timestamp
            self._total_volume += trade.volume
            self._trade_count += 1
            if trade.quantity >= BLOCK_TRADE_QTY:
                self._block_count += 1
            if self._max_price is None or trade.price > self._max_price:
                self._max_price = trade.price
            if self._min_price is None or trade.price < self._min_price:
                self._min_price = trade.price
            if self._open_price is None:
                self._open_price = trade.price
            if trade.trade_type == AGGRESSOR_BUYER:
                self._buy_aggression += trade.volume
            elif trade.trade_type == AGGRESSOR_SELLER:
                self._sell_aggression += trade.volume

    def apply_book_snapshot(self, snap: PriceBookSnapshot) -> None:
        """Refreshes the best bid (Of. Compra) from a full book snapshot."""
        with self._lock:
            self._bid_prices = [lvl.price for lvl in snap.buy_levels if lvl.price > 0]

    def apply_bid_level(self, level: PriceLevel) -> None:
        """Positionally maintains the bid side for the best-bid readout."""
        if level.is_theoretical or level.side != BookSide.BUY:
            return
        pos = max(level.position, 0)
        with self._lock:
            prices = self._bid_prices
            if level.update_type in (BookUpdateType.ADD, BookUpdateType.INSERT):
                prices.insert(min(pos, len(prices)), level.price)
            elif level.update_type == BookUpdateType.EDIT:
                if pos < len(prices):
                    prices[pos] = level.price
                else:
                    prices.append(level.price)
            elif level.update_type == BookUpdateType.DELETE:
                if pos < len(prices):
                    del prices[pos]
            elif level.update_type == BookUpdateType.DELETE_FROM:
                del prices[pos:]
            # PREPARE / FLUSH / THEORIC_PRICE carry no renderable book data.

    def snapshot(self) -> TapeSnapshot:
        with self._lock:
            return TapeSnapshot(
                trades=tuple(self._trades),
                last_price=self._last_price,
                last_time=self._last_time,
                prev_close=self._prev_close,
                total_volume=self._total_volume,
                trade_count=self._trade_count,
                block_count=self._block_count,
                max_price=self._max_price,
                min_price=self._min_price,
                open_price=self._open_price,
                best_bid=self._bid_prices[0] if self._bid_prices else None,
                buy_aggression=self._buy_aggression,
                sell_aggression=self._sell_aggression,
            )


def _aggressor_cell(trade: Trade) -> Text:
    if trade.trade_type == AGGRESSOR_BUYER:
        return Text("Buyer", style="bold green")
    if trade.trade_type == AGGRESSOR_SELLER:
        return Text("Seller", style="bold red")
    return Text("Direct", style="dim")


def _bar_bg(kind: str, ratio: float) -> str:
    """Quantity-bar background hex, interpolating dark -> bright with the fill ratio."""
    ratio = min(max(ratio, 0.0), 1.0)
    strong = int(18 + ratio * 74)  # 18..92
    weak = int(strong * 0.38)
    if kind == "buy":
        return f"#{strong:02x}{weak:02x}{weak:02x}"
    if kind == "sell":
        return f"#{weak:02x}{weak:02x}{strong:02x}"
    return f"#{weak:02x}{weak:02x}{int(strong * 0.72):02x}"  # blue-ish, direct trades


def _qty_cell(trade: Trade, max_qty: int) -> Text:
    """Qty with a Profit-style background bar, tinted by the aggressor side."""
    cell = f"{fmt_qty(trade.quantity):>{QTY_BAR_WIDTH}}"
    ratio = trade.quantity / max_qty if max_qty else 0.0
    split = QTY_BAR_WIDTH - round(QTY_BAR_WIDTH * ratio)
    if trade.trade_type == AGGRESSOR_BUYER:
        kind = "buy"
    elif trade.trade_type == AGGRESSOR_SELLER:
        kind = "sell"
    else:
        kind = "neutral"
    bold = "bold " if trade.quantity >= BLOCK_TRADE_QTY else ""
    text = Text(no_wrap=True)
    text.append(cell[:split], style=bold)
    text.append(cell[split:], style=f"{bold}on {_bar_bg(kind, ratio)}".strip())
    return text


def build_header(snap: TapeSnapshot, ticker: str, exchange: str, demo: bool) -> Panel:
    # Row 1: Ticker | Last | Change | Time | mode badge.
    row1 = Text()
    row1.append(f" {ticker} ", style="bold black on cyan")
    row1.append(f" @ {exchange} ", style="bold cyan")
    row1.append("  │  ", style="dim")
    row1.append("Last ", style="dim")
    row1.append(fmt_price(snap.last_price) if snap.last_price > 0 else "--,--", style="bold white")
    row1.append("  │  ", style="dim")
    row1.append("Change ", style="dim")
    if snap.prev_close is not None and snap.last_price > 0:
        pct = (snap.last_price / snap.prev_close - 1) * 100
        sign = "+" if pct >= 0 else ""
        row1.append(f"{sign}{fmt_decimal(pct, 2)}%", style="bold green" if pct >= 0 else "bold red")
    else:
        row1.append("--,--%", style="dim")
    row1.append("  │  ", style="dim")
    row1.append("Time ", style="dim")
    row1.append(f"{snap.last_time:%H:%M:%S}" if snap.last_time else "--:--:--", style="bold white")
    row1.append("  │  ", style="dim")
    row1.append("● DEMO" if demo else "● LIVE", style="bold magenta" if demo else "bold green")

    # Row 2: Volume | Trades | High | Low | Open | Close | Bid.
    row2 = Text()
    stats: list[tuple[str, str, str]] = [
        ("Vol", fmt_volume_human(snap.total_volume), "bold yellow"),
        ("Trades", str(snap.trade_count), "bold white"),
        ("High", fmt_price(snap.max_price) if snap.max_price else "--,--", "white"),
        ("Low", fmt_price(snap.min_price) if snap.min_price else "--,--", "white"),
        ("Open", fmt_price(snap.open_price) if snap.open_price else "--,--", "white"),
        ("Close", fmt_price(snap.prev_close) if snap.prev_close else "--,--", "white"),
        ("Bid", fmt_price(snap.best_bid) if snap.best_bid else "--,--", "bold green"),
    ]
    for index, (label, value, style) in enumerate(stats):
        if index:
            row2.append("  │  ", style="dim")
        row2.append(f"{label} ", style="dim")
        row2.append(value, style=style)

    total_aggression = snap.buy_aggression + snap.sell_aggression
    buy_pct = snap.buy_aggression / total_aggression * 100 if total_aggression else 50.0
    sell_pct = 100.0 - buy_pct
    buy_blocks = round(GAUGE_WIDTH * buy_pct / 100)
    gauge = Text()
    gauge.append("Buy ", style="bold green")
    gauge.append("█" * buy_blocks, style="green")
    gauge.append("█" * (GAUGE_WIDTH - buy_blocks), style="red")
    gauge.append(" Sell", style="bold red")
    labels = Text()
    labels.append(f"Buy: {fmt_decimal(buy_pct, 1)}% ({fmt_volume_human(snap.buy_aggression)})", style="green")
    labels.append("  |  ", style="dim")
    labels.append(f"Sell: {fmt_decimal(sell_pct, 1)}% ({fmt_volume_human(snap.sell_aggression)})", style="red")

    return Panel(
        Group(row1, row2, Text(), gauge, labels),
        title=f"Times & Trades — {ticker}",
        border_style="bright_black",
    )


def build_tape_table(snap: TapeSnapshot) -> Table:
    table = Table(box=SIMPLE, expand=True, show_edge=False)
    # Native column order: Time | Buyer | Price | Quantity | Seller | Aggressor.
    table.add_column("Time", justify="right", no_wrap=True)
    table.add_column("Buyer", justify="left", no_wrap=True, min_width=12)
    table.add_column("Price", justify="right", no_wrap=True)
    table.add_column("Quantity", justify="right", no_wrap=True)
    table.add_column("Seller", justify="left", no_wrap=True, min_width=12)
    table.add_column("Aggressor", justify="left", no_wrap=True)

    if not snap.trades:
        table.add_row(Text("Waiting for trades...", style="dim italic"))
        return table

    max_qty = max(trade.quantity for trade in snap.trades)
    for trade in reversed(snap.trades):  # newest first
        base = "dim italic" if trade.is_edit else ""
        buyer_style = f"bold green {base}".strip() if trade.trade_type == AGGRESSOR_BUYER else base
        seller_style = f"bold red {base}".strip() if trade.trade_type == AGGRESSOR_SELLER else base
        price_style = f"bold {base}".strip()
        aggressor = _aggressor_cell(trade)
        if trade.is_edit:
            aggressor.stylize("dim")
        table.add_row(
            Text(fmt_time(trade.timestamp), style=base or "dim"),
            Text(broker_name(trade.buy_agent), style=buyer_style),
            Text(fmt_price(trade.price), style=price_style),
            _qty_cell(trade, max_qty),
            Text(broker_name(trade.sell_agent), style=seller_style),
            aggressor,
        )
    return table


def build_footer(snap: TapeSnapshot) -> Panel:
    left = Text()
    left.append("Total Vol: ", style="dim")
    left.append(f"R$ {fmt_volume_human(snap.total_volume)}", style="bold yellow")
    trades = f"{snap.trade_count} {'trade' if snap.trade_count == 1 else 'trades'}"
    blocks = f"{snap.block_count} {'block' if snap.block_count == 1 else 'blocks'}"
    right = Text(f"{trades} · {blocks}", style="dim")
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="center")
    grid.add_column(justify="right")
    grid.add_row(left, Text("Press Ctrl+C to exit", style="dim italic"), right)
    return Panel(grid, border_style="bright_black")


def build_layout(snap: TapeSnapshot, ticker: str, exchange: str, demo: bool) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=7),
        Layout(name="tape"),
        Layout(name="footer", size=3),
    )
    layout["header"].update(build_header(snap, ticker, exchange, demo))
    layout["tape"].update(
        Panel(
            build_tape_table(snap),
            title="Trade Tape (most recent first)",
            border_style="bright_black",
        )
    )
    layout["footer"].update(build_footer(snap))
    return layout


def run_render_loop(state: TapeState, ticker: str, exchange: str, demo: bool) -> None:
    """Owns the main thread: rebuilds the layout at ~4 fps until Ctrl+C."""
    with Live(screen=True, refresh_per_second=4) as live:
        live.update(build_layout(state.snapshot(), ticker, exchange, demo))
        while True:
            time.sleep(0.25)
            live.update(build_layout(state.snapshot(), ticker, exchange, demo))


class DemoFeed(threading.Thread):
    """Synthetic trade generator (no DLL, credentials, or Windows required).

    Fabricates public ``Trade`` dataclass instances and pushes them through
    the same ``TapeState.ingest`` path used by live ProfitDLL callbacks.
    """

    _QUANTITIES = (100, 100, 200, 300, 500, 500, 1_000, 1_000, 2_000, 3_000, 5_000)
    _NEUTRAL_TYPES = (1, 4, 8)  # cross-trade / auction / OTC — rendered as "Direct"

    def __init__(self, ticker: str, exchange: str, state: TapeState) -> None:
        super().__init__(name="demo-times-and-trades", daemon=True)
        self._asset = AssetId(ticker=ticker, exchange=exchange)
        self._state = state
        self._stop_event = threading.Event()
        self._rng = random.Random()
        self._price = 41.25
        self._trade_number = 700_000

    def run(self) -> None:
        self._state.set_prev_close(DEMO_PREV_CLOSE)
        self._emit_bid_snapshot()
        while not self._stop_event.wait(self._rng.uniform(0.15, 0.8)):
            self._emit_trade()
            if self._rng.random() < 0.4:
                self._emit_bid_snapshot()

    def stop(self) -> None:
        self._stop_event.set()

    def _emit_bid_snapshot(self) -> None:
        """Emits a small synthetic bid book so Of. Compra also moves in demo."""
        best = round(self._price - self._rng.choice((0.01, 0.02, 0.03)), 2)
        self._state.apply_book_snapshot(
            PriceBookSnapshot(
                asset=self._asset,
                buy_levels=tuple(
                    PriceLevel(
                        asset=self._asset,
                        side=BookSide.BUY,
                        update_type=BookUpdateType.FULL_BOOK,
                        position=i,
                        price=round(best - i * 0.01, 2),
                        count=self._rng.randint(1, 5),
                        quantity=self._rng.randrange(1, 100) * 100,
                    )
                    for i in range(5)
                ),
            )
        )

    def _emit_trade(self) -> None:
        self._price = round(self._price + self._rng.choice((-0.01, -0.01, 0.0, 0.01, 0.01)), 2)
        if self._rng.random() < 0.03:  # occasional block trade
            quantity = self._rng.randrange(10_000, 60_000, 100)
        else:
            quantity = self._rng.choice(self._QUANTITIES)
        roll = self._rng.random()
        if roll < 0.45:
            trade_type = AGGRESSOR_BUYER
        elif roll < 0.90:
            trade_type = AGGRESSOR_SELLER
        else:
            trade_type = self._rng.choice(self._NEUTRAL_TYPES)
        self._trade_number += 1
        self._state.ingest(
            Trade(
                asset=self._asset,
                trade_number=self._trade_number,
                price=self._price,
                quantity=quantity,
                volume=round(self._price * quantity, 2),
                buy_agent=self._rng.choice(list(BROKER_NAMES)),
                sell_agent=self._rng.choice(list(BROKER_NAMES)),
                trade_type=trade_type,
                timestamp=datetime.now(),
                is_edit=False,
            )
        )


def run_demo(args: argparse.Namespace, state: TapeState) -> int:
    feed = DemoFeed(args.ticker, args.exchange, state)
    feed.start()
    try:
        run_render_loop(state, args.ticker, args.exchange, demo=True)
    except KeyboardInterrupt:
        print("\nStopping demo feed and exiting.")
        return 0
    finally:
        feed.stop()
    return 0


def run_live(args: argparse.Namespace, state: TapeState) -> int:
    setup_dll_path()
    activation_key, user, password, _, _ = load_credentials()
    activation_key = args.activation_key or activation_key
    user = args.user or user
    password = args.password or password

    if not (activation_key and user and password):
        print(
            "Missing credentials. Please define PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, "
            "and PROFITDLL_PASSWORD in your .env file or environment (or pass "
            "--activation-key / --user / --password).",
            file=sys.stderr,
        )
        return 2

    try:
        with ProfitClient(
            activation_key=activation_key,
            user=user,
            password=password,
            mode="market_data",
        ) as client:
            # The server handshake may still be settling right after connect
            # (WAITING_SERVER); retry briefly before giving up on the reference.
            for _ in range(3):
                try:
                    state.set_prev_close(client.get_last_daily_close(args.ticker, exchange=args.exchange))
                    break
                except Exception:
                    state.set_prev_close(None)  # variation stays hidden until available
                    time.sleep(2.0)
            client.subscribe(args.ticker, exchange=args.exchange)
            client.subscribe_price_depth(args.ticker, exchange=args.exchange)  # Of. Compra

            @client.on(Event.TRADE)
            def on_trade(trade: Trade) -> None:
                state.ingest(trade)

            @client.on(Event.PRICE_SNAPSHOT)
            def on_book_snapshot(snap: PriceBookSnapshot) -> None:
                state.apply_book_snapshot(snap)

            @client.on(Event.PRICE_LEVEL)
            def on_bid_level(level: PriceLevel) -> None:
                state.apply_bid_level(level)

            try:
                run_render_loop(state, args.ticker, args.exchange, demo=False)
            finally:
                for unsubscribe in (
                    client.unsubscribe,
                    client.unsubscribe_price_depth,
                ):
                    try:
                        unsubscribe(args.ticker, exchange=args.exchange)
                    except Exception:
                        pass  # best-effort teardown; disconnect() below is authoritative
    except KeyboardInterrupt:
        print("\nUnsubscribed, disconnected and exiting.")
        return 0
    except Exception as exc:
        print(f"Error running Times & Trades TUI: {exc}", file=sys.stderr)
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Real-time Times & Trades TUI (trade tape with aggression pressure gauge).",
    )
    parser.add_argument("--ticker", default="PETR4", help="Asset ticker symbol (default: PETR4).")
    parser.add_argument("--exchange", default="B", help="Exchange code (default: B for Bovespa).")
    parser.add_argument(
        "--demo",
        "--mock",
        dest="demo",
        action="store_true",
        help="Run with a synthetic feed (no DLL, credentials, or Windows needed).",
    )
    parser.add_argument("--activation-key", default=None, help="Override the activation key from .env.")
    parser.add_argument("--user", default=None, help="Override the user from .env.")
    parser.add_argument("--password", default=None, help="Override the password from .env.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = TapeState()
    if args.demo:
        return run_demo(args, state)
    return run_live(args, state)


if __name__ == "__main__":
    raise SystemExit(main())
