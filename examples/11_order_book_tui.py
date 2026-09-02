"""Full Level-2 Order Book (DOM) TUI with split bid/ask view.

Replicates Nelogica Profit's "Livro de Ofertas Completo" (full offer book):
a native-style summary bar (Last, Change, Time, Volume, Trades, High, Low,
Open, Close, Bid, Ask) above a side-by-side mirrored book — bids on the left
in green (Time | Broker | Qty | Bid), asks on the right in red (Ask | Qty |
Broker | Time) — featuring top-of-book highlighting, proportional quantity
bars behind each quantity, a spread indicator (R$ and bps) and side totals
(Bids Total / Asks Total).

Live mode subscribes to the aggregated price depth feed
(`subscribe_price_depth`) for the book, to the trade feed (`subscribe`) and
to the official daily candle (`Event.DAILY`) for the summary bar: session
aggregates (Volume/Trades/High/Low/Open) prefer the daily candle, falling
back to measurements from the first observed trade onwards while no candle
has arrived. The DLL keeps one price group per price, so the local book is
price-keyed: incremental updates for a known price refresh it in place, and
a reconciliation thread re-reads the DLL book whenever the level count
drifts (snapshot events are capped at 50 levels per side by the wrapper,
while the DLL exposes the full depth). The public `PriceLevel` events carry
the number of orders per level but no per-broker tags (the wrapper does not
expose the offer-book broker codes yet), so the Broker column shows the
order count per level in live mode; `--demo` renders synthetic broker names
instead.

Thread model: ProfitDLL callbacks arrive on the wrapper's dispatcher thread;
handlers only mutate a lock-guarded book state, while the main thread owns
the `rich` rendering loop.

Prerequisites (live mode):
  * Windows 64-bit OS with Python 64-bit;
  * ProfitDLL binary available (defined via PROFITDLL_PATH env var or inside `dll/`);
  * Credentials set in `.env` file or environment variables.

Demo mode (`--demo`) needs none of the above: a synthetic feed fabricates
public `PriceLevel` events and full book images, driving the exact same
rendering pipeline, so the TUI can be previewed on any OS.

Execution:

    uv run --extra tui python examples/11_order_book_tui.py --demo
    uv run --extra tui python examples/11_order_book_tui.py --ticker PETR4
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import (
    AssetId,
    BookSide,
    BookUpdateType,
    DailyCandle,
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

WALL_QTY = 5_000        # quantity above which a level's quantity renders bold
DEPTH_ROWS = 10         # levels rendered per side
MAX_BOOK_ROWS = 15      # demo feed book depth cap
QTY_BAR_WIDTH = 8       # fixed width of the quantity cell (background bar canvas)
DEMO_PREV_CLOSE = 40.80  # synthetic previous close used by --demo


def broker_name(agent_code: int) -> str:
    """Maps a B3 broker/agent code to a display name (raw code if unknown)."""
    return BROKER_NAMES.get(agent_code, str(agent_code))


def fmt_price(value: float) -> str:
    """Formats BRL as ``R$ 41,25`` (pt-BR decimal comma, thousands dot)."""
    return f"{value:,.2f}".translate(str.maketrans(",.", ".,"))


def fmt_qty(value: int) -> str:
    """Formats a quantity with pt-BR thousands separators (``5.000``)."""
    return f"{value:,}".replace(",", ".")


def fmt_decimal(value: float, decimals: int = 2) -> str:
    """Formats a plain number with pt-BR decimal comma (``+1,10`` / ``7,3``)."""
    return f"{value:.{decimals}f}".replace(".", ",")


def fmt_qty_compact(value: int) -> str:
    """Compact quantity as in Profit's book (``600``, ``2,30k``, ``13,10k``)."""
    if value >= 1_000_000:
        return fmt_decimal(value / 1_000_000) + "M"
    if value >= 1_000:
        return fmt_decimal(value / 1_000) + "k"
    return str(value)


def fmt_volume_human(value: float) -> str:
    """Human-friendly financial volume (``3,55B``, ``19,97M``, ``842K``)."""
    if value >= 1_000_000_000:
        return fmt_decimal(value / 1_000_000_000) + "B"
    if value >= 1_000_000:
        return fmt_decimal(value / 1_000_000) + "M"
    if value >= 1_000:
        return fmt_decimal(value / 1_000) + "K"
    return f"{value:.0f}"


def fmt_time(moment: datetime) -> str:
    """Formats a timestamp as ``HH:MM:SS.mmm``."""
    return f"{moment:%H:%M:%S}.{moment.microsecond // 1000:03d}"


@dataclass(frozen=True)
class BookRow:
    """Client-side view of one book level (rendering-friendly)."""

    price: float
    quantity: int
    count: int
    broker: str | None  # populated in demo mode only
    updated_at: datetime


class BookState:
    """Thread-safe Level-2 book maintained from snapshots plus incremental updates.

    ``apply_snapshot`` / ``apply_level`` run on the ProfitDLL dispatcher thread
    (live mode) or on the demo feed thread; ``snapshot`` runs on the main
    rendering thread. Index 0 is always the top of book (best bid / best ask).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bids: list[BookRow] = []
        self._asks: list[BookRow] = []

    def apply_snapshot(self, snap: PriceBookSnapshot) -> None:
        now = datetime.now()
        with self._lock:
            self._bids = [
                BookRow(level.price, level.quantity, level.count, None, now)
                for level in snap.buy_levels
            ]
            self._asks = [
                BookRow(level.price, level.quantity, level.count, None, now)
                for level in snap.sell_levels
            ]

    def load_rows(self, bids: list[BookRow], asks: list[BookRow]) -> None:
        """Replaces the whole book (demo feed full-image rebuild path)."""
        with self._lock:
            self._bids = list(bids)
            self._asks = list(asks)

    def replace_side(self, rows: list[BookRow], side: BookSide) -> None:
        """Replaces one side wholesale (live-mode reconciliation path)."""
        with self._lock:
            if side == BookSide.BUY:
                self._bids = list(rows)
            else:
                self._asks = list(rows)

    def level_count(self, side: BookSide) -> int:
        with self._lock:
            return len(self._bids if side == BookSide.BUY else self._asks)

    def apply_level(self, level: PriceLevel, *, broker: str | None = None) -> None:
        if level.is_theoretical:
            return
        rows = self._bids if level.side == BookSide.BUY else self._asks
        row = BookRow(level.price, level.quantity, level.count, broker, datetime.now())
        pos = max(level.position, 0)
        with self._lock:
            # The DLL keeps one price group per price, so an update for a
            # known price refreshes it in place instead of adding a row.
            existing = (
                next((i for i, r in enumerate(rows) if r.price == level.price), None)
                if level.price > 0
                else None
            )
            if level.update_type in (BookUpdateType.ADD, BookUpdateType.INSERT):
                if existing is not None:
                    rows[existing] = row
                else:
                    rows.insert(min(pos, len(rows)), row)
            elif level.update_type == BookUpdateType.EDIT:
                if existing is not None:
                    rows[existing] = row
                elif pos < len(rows):
                    rows[pos] = row
                else:
                    rows.append(row)
            elif level.update_type == BookUpdateType.DELETE:
                if pos < len(rows):
                    del rows[pos]  # delete events carry price=0.0; positional only
            elif level.update_type == BookUpdateType.DELETE_FROM:
                del rows[pos:]
            # PREPARE / FLUSH / THEORIC_PRICE carry no renderable book data.

    def snapshot(self) -> tuple[list[BookRow], list[BookRow]]:
        with self._lock:
            bids = sorted(self._bids, key=lambda r: r.price, reverse=True)
            asks = sorted(self._asks, key=lambda r: r.price)
        return self._collapse(bids), self._collapse(asks)

    @staticmethod
    def _collapse(rows: list[BookRow]) -> list[BookRow]:
        """Merges residual same-price rows (defensive; the DLL emits one group per price)."""
        merged: dict[float, BookRow] = {}
        for row in rows:
            if row.price in merged:
                prev = merged[row.price]
                merged[row.price] = replace(
                    prev, quantity=prev.quantity + row.quantity, count=prev.count + row.count
                )
            else:
                merged[row.price] = row
        return list(merged.values())


@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable session statistics consumed by the rendering thread."""

    last_price: float
    last_time: datetime | None
    total_volume: float
    trade_count: int
    max_price: float | None
    min_price: float | None
    open_price: float | None
    prev_close: float | None


class MarketStats:
    """Thread-safe session statistics fed by the trade feed (summary bar).

    Session aggregates (Volume/Trades/High/Low/Open) prefer the official
    daily candle pushed by the DLL (`Event.DAILY`); while none has arrived
    they are measured from the first trade observed after subscribing. Last
    and Time always follow the latest trade, falling back to the daily close
    while the trade feed is silent (e.g. closed market). ``ingest`` and
    ``apply_daily`` run on the dispatcher thread (live) or on the demo feed
    thread; ``snapshot`` runs on the main rendering thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_price = 0.0
        self._last_time: datetime | None = None
        self._total_volume = 0.0
        self._trade_count = 0
        self._max_price: float | None = None
        self._min_price: float | None = None
        self._open_price: float | None = None
        self._prev_close: float | None = None
        self._daily: DailyCandle | None = None

    def set_prev_close(self, close: float | None) -> None:
        with self._lock:
            self._prev_close = close if close and close > 0 else None

    def apply_daily(self, candle: DailyCandle) -> None:
        with self._lock:
            self._daily = candle

    def ingest(self, trade: Trade) -> None:
        with self._lock:
            if trade.is_edit:
                return  # corrections do not affect session statistics
            self._last_price = trade.price
            self._last_time = trade.timestamp
            self._total_volume += trade.volume
            self._trade_count += 1
            if self._max_price is None or trade.price > self._max_price:
                self._max_price = trade.price
            if self._min_price is None or trade.price < self._min_price:
                self._min_price = trade.price
            if self._open_price is None:
                self._open_price = trade.price

    def snapshot(self) -> MarketSnapshot:
        with self._lock:
            daily = self._daily
            last_price = self._last_price
            if last_price <= 0 and daily is not None:
                last_price = daily.close  # official session last while no trade arrived
            return MarketSnapshot(
                last_price=last_price,
                last_time=self._last_time,
                total_volume=daily.volume if daily is not None else self._total_volume,
                trade_count=daily.trades if daily is not None else self._trade_count,
                max_price=daily.high if daily is not None and daily.high > 0 else self._max_price,
                min_price=daily.low if daily is not None and daily.low > 0 else self._min_price,
                open_price=daily.open if daily is not None and daily.open > 0 else self._open_price,
                prev_close=self._prev_close,
            )


def _bar_bg(is_bid: bool, ratio: float) -> str:
    """Quantity-bar background hex, interpolating dark -> bright with the fill ratio."""
    ratio = min(max(ratio, 0.0), 1.0)
    strong = int(18 + ratio * 74)  # 18..92
    weak = int(strong * 0.38)
    return f"#{strong:02x}{weak:02x}{weak:02x}" if is_bid else f"#{weak:02x}{weak:02x}{strong:02x}"


def _qty_cell(row: BookRow, side_max: int, is_bid: bool) -> Text:
    """Qty with a Profit-style background bar filling with the side's max quantity."""
    cell = f"{fmt_qty_compact(row.quantity):>{QTY_BAR_WIDTH}}"
    ratio = row.quantity / side_max if side_max else 0.0
    split = QTY_BAR_WIDTH - round(QTY_BAR_WIDTH * ratio)
    bold = "bold " if row.quantity >= WALL_QTY else ""
    text = Text(no_wrap=True)
    text.append(cell[:split], style=bold)
    text.append(cell[split:], style=f"{bold}on {_bar_bg(is_bid, ratio)}".strip())
    return text


def _row_style(index: int, is_bid: bool) -> str:
    if index == 0:
        return "bold on #1f6f1f" if is_bid else "bold on #6f1f1f"  # top of book
    return ""


def build_side_table(rows: list[BookRow], *, is_bid: bool, has_brokers: bool) -> Table:
    table = Table(box=SIMPLE, expand=True, show_edge=False)
    broker_header = "Broker" if has_brokers else "Orders"
    side_max = max((row.quantity for row in rows[:DEPTH_ROWS]), default=0)
    price_color = "green" if is_bid else "red"

    # Native column order — Bids: Time | Broker | Qty | Bid (outer → centre);
    # Asks mirrored: Ask | Qty | Broker | Time.
    if is_bid:
        table.add_column("Time", justify="right", no_wrap=True)
        table.add_column(broker_header, justify="left", no_wrap=True, min_width=12)
        table.add_column("Qty", justify="right", no_wrap=True)
        table.add_column("Bid", justify="right", no_wrap=True)
    else:
        table.add_column("Ask", justify="right", no_wrap=True)
        table.add_column("Qty", justify="right", no_wrap=True)
        table.add_column(broker_header, justify="left", no_wrap=True, min_width=12)
        table.add_column("Time", justify="right", no_wrap=True)

    if not rows:
        table.add_row(Text("Waiting for book...", style="dim italic"))
        return table

    for index, row in enumerate(rows[:DEPTH_ROWS]):
        style = _row_style(index, is_bid)
        time_style = style or "dim"
        price_style = f"bold {price_color} {style}".strip()
        qty = _qty_cell(row, side_max, is_bid)
        broker_cell = Text(row.broker if row.broker is not None else str(row.count), style=style)
        if is_bid:
            table.add_row(
                Text(fmt_time(row.updated_at), style=time_style),
                broker_cell,
                qty,
                Text(fmt_price(row.price), style=price_style),
            )
        else:
            table.add_row(
                Text(fmt_price(row.price), style=price_style),
                qty,
                broker_cell,
                Text(fmt_time(row.updated_at), style=time_style),
            )
    return table


def build_header(
    bids: list[BookRow],
    asks: list[BookRow],
    stats: MarketSnapshot,
    ticker: str,
    exchange: str,
    demo: bool,
) -> Panel:
    # Row 1: Ticker | Last | Change | Time | Spread | mode badge.
    row1 = Text()
    row1.append(f" {ticker} ", style="bold black on cyan")
    row1.append(f" @ {exchange} ", style="bold cyan")
    row1.append("  │  ", style="dim")
    row1.append("Last ", style="dim")
    row1.append(fmt_price(stats.last_price) if stats.last_price > 0 else "--,--", style="bold white")
    row1.append("  │  ", style="dim")
    row1.append("Change ", style="dim")
    if stats.prev_close is not None and stats.last_price > 0:
        pct = (stats.last_price / stats.prev_close - 1) * 100
        sign = "+" if pct >= 0 else ""
        row1.append(f"{sign}{fmt_decimal(pct, 2)}%", style="bold green" if pct >= 0 else "bold red")
    else:
        row1.append("--,--%", style="dim")
    row1.append("  │  ", style="dim")
    row1.append("Time ", style="dim")
    row1.append(f"{stats.last_time:%H:%M:%S}" if stats.last_time else "--:--:--", style="bold white")
    row1.append("  │  ", style="dim")
    if bids and asks:
        spread = asks[0].price - bids[0].price  # 0 = locked, < 0 = crossed book
        if spread > 0:
            bps = fmt_decimal(spread / asks[0].price * 10_000, 1)
            row1.append(f"Spread {fmt_price(spread)} ({bps} bps)", style="bold yellow")
        else:
            row1.append(f"Spread {fmt_price(spread)}", style="bold yellow")
    else:
        row1.append("Spread --", style="dim")
    row1.append("  │  ", style="dim")
    row1.append("● DEMO" if demo else "● LIVE", style="bold magenta" if demo else "bold green")

    # Row 2: Volume | Trades | High | Low | Open | Close | Bid | Ask
    # (labels kept compact so all twelve native fields fit on one line).
    row2 = Text()
    summary: list[tuple[str, str, str]] = [
        ("Vol", fmt_volume_human(stats.total_volume), "bold yellow"),
        ("Trades", str(stats.trade_count), "bold white"),
        ("High", fmt_price(stats.max_price) if stats.max_price else "--,--", "white"),
        ("Low", fmt_price(stats.min_price) if stats.min_price else "--,--", "white"),
        ("Open", fmt_price(stats.open_price) if stats.open_price else "--,--", "white"),
        ("Close", fmt_price(stats.prev_close) if stats.prev_close else "--,--", "white"),
        ("Bid", fmt_price(bids[0].price) if bids else "--,--", "bold green"),
        ("Ask", fmt_price(asks[0].price) if asks else "--,--", "bold red"),
    ]
    for index, (label, value, style) in enumerate(summary):
        if index:
            row2.append(" │ ", style="dim")
        row2.append(f"{label} ", style="dim")
        row2.append(value, style=style)
    return Panel(Group(row1, row2), title=f"Order Book — {ticker}", border_style="bright_black")


def build_footer(bids: list[BookRow], asks: list[BookRow]) -> Panel:
    buy = Text()
    buy.append("Bids Total: ", style="dim")
    buy.append(fmt_qty(sum(row.quantity for row in bids)), style="bold green")
    sell = Text()
    sell.append("Asks Total: ", style="dim")
    sell.append(fmt_qty(sum(row.quantity for row in asks)), style="bold red")
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="center")
    grid.add_column(justify="right")
    grid.add_row(buy, Text("Press Ctrl+C to exit", style="dim italic"), sell)
    return Panel(grid, border_style="bright_black")


def build_layout(
    state: BookState,
    stats: MarketStats,
    ticker: str,
    exchange: str,
    demo: bool,
) -> Layout:
    bids, asks = state.snapshot()
    has_brokers = any(row.broker is not None for row in bids + asks)

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=5),
        Layout(name="book"),
        Layout(name="footer", size=3),
    )
    layout["book"].split_row(Layout(name="bids"), Layout(name="asks"))
    layout["header"].update(build_header(bids, asks, stats.snapshot(), ticker, exchange, demo))
    layout["bids"].update(
        Panel(
            build_side_table(bids, is_bid=True, has_brokers=has_brokers),
            title="BIDS",
            border_style="green",
            subtitle=f"{len(bids)} levels",
        )
    )
    layout["asks"].update(
        Panel(
            build_side_table(asks, is_bid=False, has_brokers=has_brokers),
            title="ASKS",
            border_style="red",
            subtitle=f"{len(asks)} levels",
        )
    )
    layout["footer"].update(build_footer(bids, asks))
    return layout


def run_render_loop(
    state: BookState,
    stats: MarketStats,
    ticker: str,
    exchange: str,
    demo: bool,
    reconciler: Callable[[], None] | None = None,
) -> None:
    """Owns the main thread: rebuilds the layout at ~4 fps until Ctrl+C."""
    with Live(screen=True, refresh_per_second=4) as live:
        live.update(build_layout(state, stats, ticker, exchange, demo))
        next_reconcile = time.monotonic() + 2.0
        while True:
            time.sleep(0.25)
            if reconciler is not None and time.monotonic() >= next_reconcile:
                try:
                    reconciler()
                except Exception:
                    pass  # best-effort healing; the next cycle retries
                next_reconcile = time.monotonic() + 5.0
            live.update(build_layout(state, stats, ticker, exchange, demo))


class DemoBookFeed(threading.Thread):
    """Synthetic Level-2 book generator (no DLL, credentials, or Windows required).

    Maintains an internal book model, then feeds ``BookState``/``MarketStats``
    through the same paths used by live ProfitDLL callbacks: full book images
    on mid moves, public ``PriceLevel`` events (with broker tags) on
    incremental updates, and ``Trade`` events at the touched side.
    """

    _LEVELS_PER_SIDE = 12

    def __init__(self, ticker: str, exchange: str, state: BookState, stats: MarketStats) -> None:
        super().__init__(name="demo-order-book", daemon=True)
        self._asset = AssetId(ticker=ticker, exchange=exchange)
        self._state = state
        self._stats = stats
        self._stop_event = threading.Event()
        self._rng = random.Random()
        self._bids: list[BookRow] = []
        self._asks: list[BookRow] = []
        self._best_bid = 41.23
        self._best_ask = 41.27
        self._trade_number = 700_000

    def run(self) -> None:
        self._stats.set_prev_close(DEMO_PREV_CLOSE)
        self._rebuild()
        self._push_model()
        while not self._stop_event.wait(self._rng.uniform(0.2, 0.7)):
            if self._rng.random() < 0.12:
                self._rebuild()  # mid moved: re-emit a full book image
                self._push_model()
            else:
                self._perturb()
            if self._rng.random() < 0.6:
                self._emit_trade()

    def _emit_trade(self) -> None:
        """Emits a synthetic trade at the touched side (fills the summary bar)."""
        buyer_aggressor = self._rng.random() < 0.5
        price = self._asks[0].price if buyer_aggressor else self._bids[0].price
        quantity = self._rng.choice((100, 100, 200, 500, 1_000, 1_000, 5_000))
        self._trade_number += 1
        self._stats.ingest(
            Trade(
                asset=self._asset,
                trade_number=self._trade_number,
                price=price,
                quantity=quantity,
                volume=round(price * quantity, 2),
                buy_agent=self._rng.choice(list(BROKER_NAMES)),
                sell_agent=self._rng.choice(list(BROKER_NAMES)),
                trade_type=2 if buyer_aggressor else 3,
                timestamp=datetime.now(),
                is_edit=False,
            )
        )

    def stop(self) -> None:
        self._stop_event.set()

    def _new_row(self, price: float) -> BookRow:
        quantity = self._rng.randrange(2, 180) * 100
        if self._rng.random() < 0.15:  # occasional wall
            quantity += self._rng.randrange(5_000, 25_000, 100)
        return BookRow(
            price=price,
            quantity=quantity,
            count=self._rng.randint(1, 8),
            broker=broker_name(self._rng.choice(list(BROKER_NAMES))),
            updated_at=datetime.now(),
        )

    def _rebuild(self) -> None:
        self._best_bid = round(self._best_bid + self._rng.choice((-0.01, 0.0, 0.01)), 2)
        self._best_ask = round(self._best_bid + self._rng.choice((0.02, 0.03, 0.04, 0.05)), 2)
        self._bids = [self._new_row(round(self._best_bid - i * 0.01, 2)) for i in range(self._LEVELS_PER_SIDE)]
        self._asks = [self._new_row(round(self._best_ask + i * 0.01, 2)) for i in range(self._LEVELS_PER_SIDE)]

    def _perturb(self) -> None:
        is_bid = self._rng.random() < 0.5
        rows = self._bids if is_bid else self._asks
        side = BookSide.BUY if is_bid else BookSide.SELL
        if not rows:
            self._rebuild()
            self._push_model()
            return
        index = self._rng.randrange(min(len(rows), 8))
        action = self._rng.choices(("edit", "delete", "insert", "wall"), weights=(6, 2, 1, 2))[0]

        if action in ("edit", "wall"):
            row = rows[index]
            delta = self._rng.randrange(5_000, 20_000, 100) if action == "wall" else self._rng.randrange(-40, 41) * 100
            rows[index] = replace(row, quantity=max(100, row.quantity + delta), updated_at=datetime.now())
            self._emit_level(side, BookUpdateType.EDIT, index, rows[index])
        elif action == "delete":
            rows.pop(index)
            self._emit_level(side, BookUpdateType.DELETE, index, None)
        elif action == "insert" and len(rows) < MAX_BOOK_ROWS:
            step = 0.01 if is_bid else -0.01
            row = self._new_row(round(rows[-1].price - step, 2))
            rows.append(row)
            self._emit_level(side, BookUpdateType.INSERT, len(rows) - 1, row)

    def _emit_level(
        self,
        side: BookSide,
        update_type: BookUpdateType,
        position: int,
        row: BookRow | None,
    ) -> None:
        self._state.apply_level(
            PriceLevel(
                asset=self._asset,
                side=side,
                update_type=update_type,
                position=position,
                price=row.price if row is not None else 0.0,
                count=row.count if row is not None else 0,
                quantity=row.quantity if row is not None else 0,
            ),
            broker=row.broker if row is not None else None,
        )

    def _push_model(self) -> None:
        self._state.load_rows(self._bids, self._asks)


def run_demo(args: argparse.Namespace, state: BookState, stats: MarketStats) -> int:
    feed = DemoBookFeed(args.ticker, args.exchange, state, stats)
    feed.start()
    try:
        run_render_loop(state, stats, args.ticker, args.exchange, demo=True)
    except KeyboardInterrupt:
        print("\nStopping demo feed and exiting.")
        return 0
    finally:
        feed.stop()
    return 0


def build_reconciler(
    client: ProfitClient,
    ticker: str,
    exchange: str,
    state: BookState,
) -> Callable[[], None]:
    """Builds the live-mode book reconciler run periodically by the render loop.

    Snapshot events are capped at 50 levels per side by the wrapper while the
    DLL exposes the full depth, so the first pass expands the book; later
    passes re-read the DLL book only when the local level count drifts,
    healing positional mistakes caused by missed delete/update events.
    """

    def reconcile() -> None:
        for side in (BookSide.BUY, BookSide.SELL):
            count = client.get_price_depth_side_count(ticker, side, exchange=exchange)
            if state.level_count(side) == count:
                continue
            now = datetime.now()
            rows = []
            for position in range(count):
                level = client.get_price_group(ticker, side, position, exchange=exchange)
                if level.is_theoretical or level.price <= 0:
                    continue
                rows.append(BookRow(level.price, level.quantity, level.count, None, now))
            state.replace_side(rows, side)

    return reconcile


def run_live(args: argparse.Namespace, state: BookState, stats: MarketStats) -> int:
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
                    stats.set_prev_close(client.get_last_daily_close(args.ticker, exchange=args.exchange))
                    break
                except Exception:
                    stats.set_prev_close(None)  # variation stays hidden until available
                    time.sleep(2.0)
            client.subscribe_price_depth(args.ticker, exchange=args.exchange)
            client.subscribe(args.ticker, exchange=args.exchange)  # summary bar stats

            @client.on(Event.PRICE_SNAPSHOT)
            def on_snapshot(snap: PriceBookSnapshot) -> None:
                state.apply_snapshot(snap)

            @client.on(Event.PRICE_LEVEL)
            def on_level(level: PriceLevel) -> None:
                state.apply_level(level)

            @client.on(Event.TRADE)
            def on_trade(trade: Trade) -> None:
                stats.ingest(trade)

            @client.on(Event.DAILY)
            def on_daily(candle: DailyCandle) -> None:
                stats.apply_daily(candle)  # official session stats for the summary bar

            try:
                run_render_loop(
                    state,
                    stats,
                    args.ticker,
                    args.exchange,
                    demo=False,
                    reconciler=build_reconciler(client, args.ticker, args.exchange, state),
                )
            finally:
                for unsubscribe in (
                    client.unsubscribe_price_depth,
                    client.unsubscribe,
                ):
                    try:
                        unsubscribe(args.ticker, exchange=args.exchange)
                    except Exception:
                        pass  # best-effort teardown; disconnect() below is authoritative
    except KeyboardInterrupt:
        print("\nUnsubscribed, disconnected and exiting.")
        return 0
    except Exception as exc:
        print(f"Error running Order Book TUI: {exc}", file=sys.stderr)
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Full Level-2 Order Book (DOM) TUI with split bid/ask view.",
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
    state = BookState()
    stats = MarketStats()
    if args.demo:
        return run_demo(args, state, stats)
    return run_live(args, state, stats)


if __name__ == "__main__":
    raise SystemExit(main())
