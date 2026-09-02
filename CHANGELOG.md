# Changelog

All notable changes to `profitdll-wrapper` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-09-02

### Fixed

- **Order routing used the login password instead of the routing password**
  (critical incident): every order-routing call
  (`send_*`, `cancel_*`, `change_order`, `zero_position`) sent the login
  password where the manual requires the *plain text routing password*, so
  the order server (Hades) dropped orders silently and repeated attempts
  locked the account. `load_credentials()` now loads `routing_key`
  (`PROFITDLL_ROUTING_KEY`/`ROUTING_KEY`), `ProfitClient` accepts
  `routing_password=` (used as the default for all routing calls, still
  overridable per call) and refuses to construct with `mode="routing"`
  without it. Examples 04/06/07 pass the routing key explicitly and abort
  when it is missing. The two credentials are never conflated: no code path
  falls back to the login password as the routing password.
- `StopPrice` is now `-1.0` for non-stop orders in `SendOrder` (manual:
  "non-stop orders should be -1"; was `0.0`).
- `TConnectorCancelOrder.Version`/`TConnectorChangeOrder.Version` set to `0`
  (manual: "Supported: 0"; were `1` — correlates with the observed
  `cancel_order` hang). `TConnectorZeroPosition.Version` set to `1`
  (manual: "Supported: 0 .. 1"; was `2`).
- `get_order_history()` now maps order statuses through the `OrderStatus`
  enum (1=PartiallyFilled, 2=Filled, 4=Canceled, 8=Rejected); the previous
  ad-hoc map reported wrong statuses.
- Example `07_watchdog_and_reconciliation.py` had a `SyntaxError` (docstring
  opening with `""`); example `06_trading_bot_sample.py` called a
  non-existent `client.send_order()`.

### Added

- New dedicated example `12_list_accounts.py`: enumerates every trading
  account (and sub-account) linked to the DLL login via `get_accounts()`,
  printing owner, broker, decoded `AccountType` and account flags, retrying
  briefly while the roster arrives from the routing server, and validating
  the `.env` account against the roster. `AccountType` is now exported from
  the package root.
- `TradingMessageResultCode` (mrc codes) is now exported from the package and
  documented with the order acceptance chain
  (`SENT_TO_HADES_PROXY -> … -> ACCEPTED`); example `04_send_order.py`
  prints it for every `TRADING_MESSAGE` event and validates the target
  account against the DLL roster before sending.
- `send_*` docstrings now state that the return value is the session-scoped
  local order ID, not the permanent Profit order ID.

## [0.2.0] - 2026-08-25

### Added

- Two `rich`-based TUI examples replicating Profit's native windows, each with
  the full native-style summary bar (Last, Change, Time, Volume, Trades,
  High/Low, Open, Close, Bid/Ask): `10_times_and_trades_tui.py`
  (trade tape with native column order, aggressor-side highlighting,
  proportional quantity bars and a buy/sell aggression pressure gauge) and
  `11_order_book_tui.py` (full L2 DOM with mirrored bid/ask sides,
  spread indicator and top-of-book highlight). Both accept a `--demo` / `--mock` synthetic feed that runs
  without the DLL, credentials, or Windows, and are installed via the new
  `tui` optional extra (`uv sync --extra tui`).
- Portuguese (pt-BR) README (`README.pt-BR.md`) with a language selector in both
  READMEs; the examples section now lists all eleven `examples/` scripts; new
  "Feedback" section linking to the issue chooser.
- GitHub issue templates (bug report, feature request) and issue-chooser contact
  links (docs site, PyPI, security policy).
- MkDocs documentation site deployed to GitHub Pages by the new `docs.yml`
  workflow (`mkdocs build --strict` + `actions/deploy-pages`).
- Prominent "unofficial / not affiliated with Nelogica" and no-financial-liability
  disclaimers in README, docs index, SECURITY.md, and the package description.
- Renamed PyPI package to `profitdll-wrapper` and module to `profitdll_wrapper`.
- GitHub Actions publish workflow (`publish.yml`) releasing to PyPI via
  Trusted Publishing (OIDC, no API token) on GitHub Releases / `v*` tags.

### Changed

- Documentation links (READMEs and the `Documentation` URL in `pyproject.toml`)
  now point to the GitHub Pages site instead of repository blobs; the pt-BR
  README ships in the sdist.
- Replaced the "unofficial" wording with "independent, community-maintained" in
  README, docs, SECURITY.md, and the package description; the not-affiliated
  disclaimers remain.
- README installation instructions now target PyPI (`pip install` / `uv add`,
  with optional extras documented); the source checkout moved to the
  Development section.
- Package version is now read dynamically from `profitdll_wrapper.__version__`
  (single source of truth; no more manual `pyproject.toml` bumps).
- sdist now ships `examples/`, `docs/`, `mkdocs.yml`, `.env.example`,
  `docker-compose.yml`, and `SECURITY.md` so source builds can follow every
  workflow the README documents.
- Dropped the deprecated `License :: OSI Approved :: MIT License` classifier
  (the PEP 639 SPDX `license = "MIT"` expression supersedes it).

### Fixed

- Price depth events now carry real book data: `TConnectorPriceGroup.Count`
  and `Quantity` were widened to 64-bit (`c_int64`) to match the DLL's Delphi
  x64 layout — previously `count`/`quantity` decoded as `0` because the
  32-bit field reads landed on inter-field padding.
- The price-depth callback now reads levels via `GetPriceGroup` instead of
  enqueueing placeholders: `PRICE_LEVEL` events carry price/count/quantity
  (plus the theoretical flag) and `PRICE_SNAPSHOT` events carry a populated
  book (bounded at 50 levels per side) instead of empty tuples. Delete and
  rebuild update types remain positional-only, without querying the DLL.
- `docs/README.md` linked the repository-root README via `../README.md`, which
  broke `mkdocs build --strict` (target outside `docs_dir`); it now links to the
  GitHub README URL instead.
- Package is importable on non-Windows platforms again: `WINFUNCTYPE` (Windows-only
  in `ctypes`) is now aliased to `CFUNCTYPE` outside Windows, so Linux CI legs and
  cross-platform imports work; connecting still raises `PlatformNotSupportedError`.
- `test_load_dll_success_calls_windll` patches `ctypes.WinDLL` with
  `raising=False` so the Windows simulation also runs on Linux CI runners.
- CI lint job (Ubuntu) now type-checks with `platform = "win32"`: `ctypes.WinDLL`
  and `os.add_dll_directory` only exist in typeshed for Windows targets.
- `PROFITDLL_PATH` env var name had been corrupted to
  `profitdll_wrapper_PATH` in the integration-test `simulator_env` fixture.
- Docstring cross-reference `profitdll.client.ProfitClient` corrected to
  `profitdll_wrapper.client.ProfitClient`.

## [0.1.0] - 2026-08-21

First public release. Internal iterations before this
number were never published, so versioning starts at 0.1.0.

### Security

- Removed the stale internal `profitdll_function_audit_and_roadmap.md` planning
  document (superseded by `docs/API_SURFACE.md`; all roadmap phases completed).
- Removed the vendor's copyrighted documentation from the repository tree; it must
  never be redistributed with this package.
- Removed real credentials accidentally committed to `tests/test_config.py`; the
  sdist ships `tests/`, so they would have been published to PyPI. Rotate any
  credentials that were present in local `.env` files.
- DLL loading no longer searches the bare working directory (DLL planting
  vector); resolution order is now explicit path > `PROFITDLL_PATH` > `./dll/`,
  with a warning when the working-directory fallback is used.
- Generic `USER`/`PASSWORD` are no longer read from the process environment
  (POSIX shells always define `USER`, which could be sent as the ProfitDLL
  login). Unprefixed names remain valid inside the `.env` file only;
  environment variables must be `PROFITDLL_*`-prefixed.
- Parquet sink: the `COPY ... TO` target path is now escaped, and row insertion
  uses bound parameters (`executemany`).
- `docker-compose.yml` fails fast when `TIMESCALE_PASSWORD` is unset instead of
  defaulting to `changeme`.

### Fixed

- Parquet sink was fundamentally broken (DuckDB database opened on the output
  file itself, `CREATE TABLE` without column types, and a columnar `VALUES`
  insert that never matched row shape). Rewritten with an in-memory scratch
  database, typed DDL, and `executemany`; now covered by tests.
- Repaired double-encoded (mojibake) text in 17 test files.

### Changed

- **Breaking:** `ConnectionError` renamed to `ProfitConnectionError` so
  `from profitdll_wrapper import *` no longer shadows the builtin.
- **Breaking:** `ConnectionState.ROTEAMENTO` renamed to `ConnectionState.ROUTING`
  (ABI value unchanged).
- **Breaking:** `get_theoretical_price` returns `None` instead of `0.0` when the
  DLL reports no price (0.0 is an economically meaningful quote).
- Mixins no longer bypass static typing with `self: Any`; a typed
  `_ClientBase` declares the shared state, so the public API is genuinely
  checked by `mypy --strict`. `keep_alive` is now generic (preserves callback
  types). `with ProfitClient(...) as c` infers `ProfitClient` instead of the
  core mixin.
- Library logger gained a `NullHandler` (no output unless the application
  configures logging).
- Removed dead `profitdll_wrapper/client.py` module shadowed by the `client/`
  package and four unused static wrapper methods.
- Remaining Portuguese docstrings/log messages translated to English;
  magic numbers (offer frame layout, retry counts, timeouts) named as
  constants.
- README/docs: fixed broken links, corrected test/coverage numbers, added
  coverage floor (`fail_under = 80`).

### Added

- Full order routing & custody reconciliation suite (`send_buy_order`,
  `send_sell_order`, `send_market_buy`, `send_market_sell`, `cancel_order`,
  `cancel_all_orders`, `zero_position`, `get_position`, `get_accounts`,
  `get_order_history`).
- Real-time trade streaming (P0) and positional offer book depth (P1) handlers
  with *Pure Enqueue* thread safety.
- Parquet sink tests, credential-isolation regression tests, and 223 unit &
  ABI contract tests (80%+ coverage) under `mypy --strict`, `ruff`, `pytest`,
  `bandit`, and `pip-audit`.
