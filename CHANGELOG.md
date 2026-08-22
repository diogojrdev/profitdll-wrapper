# Changelog

All notable changes to `profitdll-wrapper` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Prominent "unofficial / not affiliated with Nelogica" and no-financial-liability
  disclaimers in README, docs index, SECURITY.md, and the package description.
- Renamed PyPI package to `profitdll-wrapper` and module to `profitdll_wrapper`.
- GitHub Actions publish workflow (`publish.yml`) releasing to PyPI via
  Trusted Publishing (OIDC, no API token) on GitHub Releases / `v*` tags.

### Changed

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
