"""Command-line entry point: ``profitdll-ingest``.

Downloads historical data via ProfitDLL and persists it to a configurable
backend (SQLite, CSV, Parquet, or PostgreSQL/TimescaleDB). All settings can
be supplied either as CLI flags or via environment variables / ``.env``.

Examples::

    # Single ticker to the default SQLite DB
    profitdll-ingest --ticker VALE3 --start 01/01/2026 --end 31/01/2026

    # Multiple tickers, CSV output
    profitdll-ingest --ticker VALE3,PETR4,WDOFUT --exchange B,F,F \
        --start 01/01/2026 --end 31/01/2026 --to csv

    # A portfolio file (one "TICKER EXCHANGE" per line)
    profitdll-ingest --tickers-file portfolio.txt \
        --start 01/01/2026 --end 31/01/2026 --to postgres \
        --db-url postgresql://profit:secret@localhost:5432/profit
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from profitdll_wrapper._config import load_credentials, load_env_file, setup_dll_path
from profitdll_wrapper.client import ProfitClient

if TYPE_CHECKING:
    from profitdll_wrapper.ingest.sink import DataSink

logger = logging.getLogger("profitdll_wrapper.ingest.cli")

_DEFAULT_DATE_SUFFIX = " 00:00:00"
_EPILOG = """\
backend extras:
  sqlite/csv        always available (stdlib).
  parquet           requires: uv sync --extra parquet
  postgres          requires: uv sync --extra postgres

note:
  The Nelogica API caps historical requests at a 30-day window
  (HISTORY_PERIOD_LIMIT). For longer backfills, split the range into
  <=30-day chunks; re-runs are idempotent (UPSERT).
"""


def build_parser() -> argparse.ArgumentParser:
    """Constructs the argument parser for the ingest CLI."""
    parser = argparse.ArgumentParser(
        prog="profitdll-ingest",
        description="Download B3 historical data via ProfitDLL and persist it to a database or files.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tgt = parser.add_argument_group("tickers")
    tgt.add_argument(
        "--ticker",
        action="append",
        default=[],
        metavar="TICKER[,TICKER...]",
        help="One or more comma-separated tickers. Repeatable. Example: --ticker VALE3,PETR4.",
    )
    tgt.add_argument(
        "--tickers-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="File with one 'TICKER [EXCHANGE]' per line; blank/# lines are ignored.",
    )
    tgt.add_argument(
        "--exchange",
        action="append",
        default=[],
        metavar="CODE[,CODE...]",
        help="Exchange code(s) aligned with --ticker (e.g. B for Bovespa, F for BMF). "
        "Defaults to 'B' when fewer codes than tickers are given.",
    )

    rng = parser.add_argument_group("interval")
    rng.add_argument(
        "--start", required=True, metavar='"DD/MM/YYYY [HH:MM:SS]"', help="Interval start date."
    )
    rng.add_argument(
        "--end", required=True, metavar='"DD/MM/YYYY [HH:MM:SS]"', help="Interval end date."
    )

    out = parser.add_argument_group("output")
    out.add_argument(
        "--to",
        dest="backend",
        choices=["sqlite", "csv", "parquet", "postgres"],
        default=None,
        help="Sink backend (default: env SINK_BACKEND or 'sqlite').",
    )
    out.add_argument(
        "--db-url", default=None, help="Connection string for sqlite/postgres (env DATABASE_URL)."
    )
    out.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for csv/parquet (env CSV_OUTPUT_DIR, default ./data).",
    )
    out.add_argument(
        "--data-types",
        default="trades",
        help="Comma-separated subset of: trades,candles (default: trades).",
    )
    out.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Buffer size before flush (env BATCH_SIZE, default 500).",
    )

    run = parser.add_argument_group("runtime")
    run.add_argument(
        "--inactivity-timeout",
        type=float,
        default=None,
        help="Seconds of silence to assume a ticker's stream is done (env INACTIVITY_TIMEOUT, default 15).",
    )
    run.add_argument(
        "--max-timeout",
        type=float,
        default=None,
        help="Hard upper bound for the whole run in seconds (env MAX_TIMEOUT, default 300).",
    )
    run.add_argument(
        "-v", "--verbose", action="count", default=0, help="Increase log verbosity (-v, -vv)."
    )
    return parser


def _parse_data_types(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not parts:
        return ["trades"]
    valid = {"trades", "candles"}
    bad = [p for p in parts if p not in valid]
    if bad:
        raise SystemExit(f"Unknown data type(s): {bad}. Expected subset of {sorted(valid)}.")
    return parts


def _parse_tickers(
    ticker_args: Sequence[str], file_path: Path | None, exchanges: Sequence[str]
) -> list[tuple[str, str]]:
    """Builds the (ticker, exchange) list from CLI args and/or a tickers file.

    A tickers-file line of the form ``TICKER EXCHANGE`` fixes the exchange for
    that line; otherwise the exchange is taken positionally from --exchange or
    defaults to ``"B"``.
    """
    # Track which entries came with an explicit exchange attached.
    explicit: list[tuple[str, str | None]] = []
    for chunk in ticker_args:
        for t in chunk.split(","):
            t = t.strip()
            if t:
                explicit.append((t, None))

    if file_path is not None:
        for line in file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            explicit.append((parts[0], parts[1] if len(parts) > 1 else None))

    if not explicit:
        raise SystemExit("No tickers provided. Use --ticker and/or --tickers-file.")

    # Flatten positional exchange codes for entries without an inline one.
    positional: list[str] = []
    for chunk in exchanges:
        positional.extend(e.strip() for e in chunk.split(",") if e.strip())

    pairs: list[tuple[str, str]] = []
    pos_idx = 0
    for ticker, inline in explicit:
        if inline is not None:
            pairs.append((ticker, inline))
        elif pos_idx < len(positional):
            pairs.append((ticker, positional[pos_idx]))
            pos_idx += 1
        else:
            pairs.append((ticker, "B"))
    return pairs


def _normalize_date(value: str) -> str:
    """Appends a default time component if the user only supplied a date."""
    value = value.strip()
    if len(value) <= 10:  # "DD/MM/YYYY"
        return value + _DEFAULT_DATE_SUFFIX
    return value


@dataclass
class _EnvOverrides:
    """Typed container for settings read from the .env file."""

    backend: str | None = None
    db_url: str | None = None
    output_dir: str | None = None
    inactivity_timeout: float | None = None
    max_timeout: float | None = None
    batch_size: int | None = None


def _read_env_overrides(env: dict[str, str]) -> _EnvOverrides:
    return _EnvOverrides(
        backend=env.get("SINK_BACKEND"),
        db_url=env.get("DATABASE_URL"),
        output_dir=env.get("CSV_OUTPUT_DIR"),
        inactivity_timeout=_opt_float(env.get("INACTIVITY_TIMEOUT")),
        max_timeout=_opt_float(env.get("MAX_TIMEOUT")),
        batch_size=_opt_int(env.get("BATCH_SIZE")),
    )


def _opt_float(raw: str | None) -> float | None:
    return float(raw) if raw else None


def _opt_int(raw: str | None) -> int | None:
    return int(raw) if raw else None


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    args = build_parser().parse_args(argv)
    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(
        level=max(level, logging.DEBUG), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    env = load_env_file()
    overrides = _read_env_overrides(env)

    backend: str = args.backend or overrides.backend or "sqlite"
    db_url: str | None = args.db_url or overrides.db_url
    output_dir: Path | None = args.output_dir or (
        Path(overrides.output_dir) if overrides.output_dir else None
    )
    inactivity_timeout: float = args.inactivity_timeout or overrides.inactivity_timeout or 15.0
    max_timeout: float = args.max_timeout or overrides.max_timeout or 300.0
    batch_size: int = args.batch_size or overrides.batch_size or 500
    data_types = _parse_data_types(args.data_types)

    tickers = _parse_tickers(args.ticker, args.tickers_file, args.exchange)
    start_date = _normalize_date(args.start)
    end_date = _normalize_date(args.end)

    # Source credentials and ensure the DLL can be located. Config helpers read
    # from the default repo-root .env and process environment.
    setup_dll_path()
    creds = load_credentials()
    optional = ("account", "broker")
    missing = [k for k, v in creds.items() if k not in optional and not v]
    if missing:
        logger.error("Missing credentials: %s. Set them in .env or the environment.", missing)
        return 2

    # Build the sink via the factory (lazy-imported backends).
    from profitdll_wrapper.ingest import create_sink, ingest_history

    sink: DataSink
    try:
        if backend in ("sqlite", "postgres"):
            sink = create_sink(backend, db_url=db_url, batch_size=batch_size)
        else:  # csv / parquet
            sink = create_sink(
                backend, output_dir=output_dir or Path("./data"), batch_size=batch_size
            )
    except (ValueError, ImportError) as exc:
        logger.error("Could not create %s sink: %s", backend, exc)
        return 2

    logger.info(
        "Starting ingestion: %d ticker(s) -> %s (%s to %s), types=%s",
        len(tickers),
        backend,
        start_date,
        end_date,
        data_types,
    )

    stats = None
    client = ProfitClient(
        activation_key=creds["activation_key"],
        user=creds["user"],
        password=creds["password"],
        mode="market_data",
        broker_id=int(creds["broker"]) if creds["broker"].isdigit() else None,
    )
    try:
        with client:
            stats = ingest_history(
                client=client,
                sink=sink,
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                data_types=data_types,
                inactivity_timeout=inactivity_timeout,
                max_timeout=max_timeout,
            )
    except Exception:
        logger.exception("Ingestion failed.")
        return 1
    finally:
        sink.close()

    if stats is None:  # pragma: no cover - unreachable; except path returns early
        return 1

    print(
        f"\nIngestion complete in {stats.elapsed_seconds:.2f}s: "
        f"{stats.trades_written} trades, {stats.candles_written} candles "
        f"across {len(stats.tickers)} ticker(s)."
    )
    for ts in stats.tickers:
        flag = " [INVALID]" if ts.invalid else ""
        print(
            f"  {ts.ticker} ({ts.exchange}): {ts.trades_written} trades, {ts.candles_written} candles{flag}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
