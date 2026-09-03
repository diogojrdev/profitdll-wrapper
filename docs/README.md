# profitdll-wrapper Documentation Overview

> **Status:** v0.4.0 — market data, price depth, order routing, custody and the historical-ingestion stack (progress-callback completion, multi-window runner). This directory contains the architectural specifications, API audits, and design blueprints for `profitdll-wrapper`.
>
> **Independent community project** — not affiliated with or endorsed by Nelogica. Provided "as is" with no financial liability for trading outcomes; see the disclaimer in the [project README](https://github.com/diogojrdev/profitdll-wrapper#readme).

A modern, **idiomatic, strictly typed, and thread-safe** Python wrapper around Nelogica's ProfitDLL (native C/Delphi API using `stdcall` calling convention, featuring memory pointers and asynchronous callbacks dispatched from a dedicated native `ConnectorThread`).

The native DLL is low-level and demanding for standard Python development:

- `stdcall` calling convention, raw `PWideChar` and `Pointer` fields, packed C structs.
- Asynchronous data delivered exclusively via **callbacks executing on a native C thread** (`ConnectorThread`).
- DLL-allocated heap strings requiring **manual memory deallocation**.
- Historical 32-bit `ctypes` ABI bug when passing structs > 32 bits by value.
- Over 150 exported C functions without high-level ergonomic abstractions.

`profitdll-wrapper` encapsulates this complexity behind a clean Python interface: object-oriented client lifecycles, event dispatchers, immutable dataclasses, automatic memory safety, and static type checking.

---

## Design Principles

1. **Idiomatic** — Uses context managers (`with`), dataclasses, strict `Enum` types, and comprehensive type annotations. Raw `ctypes` objects are strictly encapsulated.
2. **Safe by Default** — Automated C memory management; callbacks safely marshalled to caller threads via thread-safe queues; error codes (`NL_*`) converted to typed Python exceptions.
3. **Pure Enqueue Architecture** — Native callbacks never issue reentrant requests: they copy data via synchronous accessors and enqueue it, preventing GIL deadlocks under intense market data throughput.
4. **Fault Isolation** — User exceptions inside event handlers are caught and logged, ensuring callback failures never crash native DLL threads.

---

## Documentation Contents

| Document | Description |
|---|---|
| [`README.md`](README.md) | Architectural overview and guide index |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Layer design, abstraction patterns, and thread-safety invariants |
| [`API_SURFACE.md`](API_SURFACE.md) | Native ProfitDLL function mapping and ABI audit |
| [`INGEST.md`](INGEST.md) | Historical data ingestion: sinks, schema, and the `profitdll-ingest` CLI |

