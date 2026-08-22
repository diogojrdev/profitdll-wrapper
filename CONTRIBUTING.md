# Contributing to `profitdll-wrapper`

Thank you for your interest in contributing! 🎉 Contributions of all kinds are welcome.

## Before You Begin

- Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) to understand design decisions and architectural invariants.
- **Golden Rule:** `ctypes` usage is strictly encapsulated within `src/profitdll_wrapper/_bindings` and `src/profitdll_wrapper/_types`. Never leak raw ctypes types or pointers to the public API surface.

## Environment Setup

This project uses [uv](https://docs.astral.sh/uv):

```bash
git clone https://github.com/diogojrdev/profitdll-wrapper.git
cd profitdll-wrapper
uv sync
```

Nelogica's native proprietary DLL is not bundled with this repository — obtain it separately from Nelogica (this project is not affiliated with them).
Most code contributions do not require the native binary as the test suite uses high-fidelity fake backends.

## Contribution Workflow

1. Create a feature branch off `main`.
2. Make your changes.
3. Validate locally:

   ```bash
   uv run ruff check
   uv run ruff format --check
   uv run mypy --strict src
   uv run pytest
   ```

4. Format commits following [Conventional Commits](https://www.conventionalcommits.org/).
5. Submit a Pull Request describing **what** was changed and **why**.

## Standards & Guidelines

- **Test Coverage:** All new features or bug fixes must include unit tests.
- **Strict Typing:** `mypy --strict` must pass cleanly without warnings.
- **Code Style:** `ruff` enforces formatting and code style.
- **Documentation:** Public classes and functions must include Google-style docstrings (processed by MkDocs/mkdocstrings).

## Reporting Bugs & Suggesting Features

Open a GitHub issue with:

- Python version and `profitdll-wrapper` version.
- Operating system details (Note: native ProfitDLL is Windows-only).
- Reproducible code steps and expected vs actual behavior.

For security issues, refer to [`SECURITY.md`](SECURITY.md) (do not create public issues).

