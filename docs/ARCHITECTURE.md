# Architecture

This document describes how `profitdll-wrapper` is layered to isolate Python developers from the native C/Pascal ProfitDLL complexity.

---

## Layer Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Public Layer  (profitdll_wrapper)                       │
│  ProfitClient, Event, dataclasses (Trade, Order, ...)    │
│  → Main public surface imported and used by application  │
├──────────────────────────────────────────────────────────┤
│  Event Dispatcher Layer  (profitdll_wrapper._events)     │
│  Dispatcher: C Callback → Thread-safe Queue → Handler   │
│  User event handling (sync or async)                     │
├──────────────────────────────────────────────────────────┤
│  Type Mapping Layer  (profitdll_wrapper._types)          │
│  ctypes ↔ dataclasses/enum conversion                    │
│  Native C struct defs, WCHAR/Unicode conversions         │
├──────────────────────────────────────────────────────────┤
│  Native Binding Layer  (profitdll_wrapper._bindings)     │
│  Pure ctypes: loads DLL binary, declares C signatures,   │
│  argtypes/restype, NL_* return error codes               │
│  → ONLY layer accessing ctypes types directly           │
├──────────────────────────────────────────────────────────┤
│  Native ProfitDLL  (32/64-bit, Delphi, stdcall)           │
└──────────────────────────────────────────────────────────┘
```

**Golden Rule:** `ctypes` usage is **strictly constrained** to `_bindings/` and `_types/`. End-user applications never touch `ctypes`. This architecture enables swapping execution backends (e.g. CFFI or Cython bindings) without breaking the public API surface.

---

## Native Binding Layer (`_bindings/`)

Responsible for loading the native DLL binary and binding explicit C signatures.

### Binary Loading & Architecture Resolution

```python
import ctypes, platform, sys

def _load_dll(explicit_path: Path | None = None) -> ctypes.WinDLL:
    if platform.system() != "Windows":
        raise PlatformNotSupportedError("ProfitDLL is Windows-only")
    # Native WinDLL uses stdcall calling convention
    return ctypes.WinDLL(str(resolved_path))
```

Critical ABI facts verified against Nelogica specifications:
- **`stdcall` Calling Convention** across 32-bit **and** 64-bit binaries → `ctypes.WinDLL` (not `CDLL`).
- Python 32-bit `bpo-41021` struct-passing bug: when passing structs larger than 32 bits by value on 32-bit x86, ctypes memory layout can corrupt stack frames. **Mitigation:** Recommend/enforce 64-bit Python runtimes; when 32-bit is required, deserialize using pointer accessor functions (`TranslateTrade`).

### Signature Binding

Every C function is assigned explicit `argtypes` and `restype` — **never** relying on ctypes default `c_int`:

```python
from ctypes import c_int, c_wchar_p, WinDLL

def bind(lib: WinDLL) -> None:
    lib.DLLInitializeLogin.argtypes = [
        c_wchar_p, c_wchar_p, c_wchar_p,           # activation, user, password
        TStateCallback, TDailyCallback, TOrderChangeCallbackV2
    ]
    lib.DLLInitializeLogin.restype = c_int          # NLCode return code
```

### `NL_*` Error Codes

Mapped to a typed| Delphi Native | ctypes | Python Model | Description / Notes |
|---|---|---|---|
| `PWideChar` | `c_wchar_p` | `str` | **UTF-16 Unicode string**; requires memory deallocation if allocated by DLL |
| `Pointer` | `c_void_p` | Opaque handle | e.g. `a_pTrade` in `TranslateTrade` |
| `^T` (pointer) | `POINTER(T)` | — | Direct structure pointer |
| `packed record` | `Structure` (`_pack_=1`) | dataclass | 1-byte alignment |

### Core C Structs

```python
class TConnectorAssetIdentifier(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("Version", c_uint16),
        ("Ticker", c_wchar_p),   # "PETR4"
        ("Exchange", c_wchar_p), # "B" (Bovespa), "F" (BMF)
        ("FeedType", c_uint8),
    ]
```

> ⚠️ **PWideChar in callback structs:** Pointers reference native memory allocated inside DLL internal buffers, valid only during callback scope. Invariants: **copy content immediately** (`.value` → `str`) and never retain raw pointers.

### String Memory Management

Functions returning heap-allocated `PWideChar` require explicit native deallocation (`DLLFreeMemory`). Standard library wrapper pattern:

```python
def _read_and_free(ptr: c_wchar_p) -> str:
    s = ptr.value             # Copy to Python str before deallocation
    _lib.DLLFreeMemory(ptr)   # Release on native DLL heap
    return s
```

---

## Event Dispatcher Layer (`_events/`) — Architectural Core

### Constraint Analysis

All market data and order events arrive via **callbacks running on Nelogica's native `ConnectorThread`**. Native API constraints:

> *"Other DLL functions should not be used within a callback."* — executing request or routing functions inside native callback scope causes undefined behavior or GIL deadlocks.
>
> Native callbacks share **a single internal execution thread**; slow handlers block all subsequent market events.
>
> Pointer accessors (`TranslateTrade`) **must** execute synchronously within callback scope before returning.

### Pure Enqueue Pattern

```
ConnectorThread (Native DLL)      Dispatcher Worker Thread              User Event Handlers
────────────────────────────      ────────────────────────              ───────────────────
TTradeCallbackV2 ──┐
                   │  1. Thin C callback: deserializes
                   │     + calls accessor (TranslateTrade)
                   ├──────── queue.put_nowait(event) ──►  2. Queue worker loop
                   │                                          3. Dispatches event
                   │                                             (sync or async)
TOfferBookCallback ┘                                          4. Fault-isolated execution
```

**Architectural Invariants:**
1. C callback handlers (`CFUNCTYPE`, stdcall) perform **minimal work**: copy fields to immutable dataclasses and push to thread-safe `queue.Queue`. `ConnectorThread` never blocks.
2. Mandatory accessors (`TranslateTrade` for V2 trade structures) run **inside** the callback before enqueuing because native pointers are only valid for callback duration.
3. A background dispatcher thread drains the queue and executes user-registered event handlers. Here, application code can safely make API requests, write to database, or call logging — completely detached from native DLL threads.
4. Unhandled exceptions inside user callbacks are caught and logged; they **never** bubble up to native C stack frames.

### Callback Lifetime & GC Keep-Alive

`ctypes` requires native `CFUNCTYPE` function wrappers to remain **referenced in memory** for the lifetime of the native DLL process to prevent Garbage Collection and segfaults. The library maintains an internal registry:

```python
_callbacks: dict[str, CFUNCTYPE] = {}

def keep_alive(name: str, fn: CFUNCTYPE) -> CFUNCTYPE:
    _callbacks[name] = fn
    return fn
```

---

## Public Client Layer (`ProfitClient`)

Facade composing underlying mixins into a single user-facing interface:

```python
class ProfitClient:
    def __init__(self, *, activation_key: str, user: str, password: str, mode: Mode = "market_data"): ...

    # Context manager lifecycle
    def connect(self, timeout: float = 30.0) -> None: ...
    def disconnect(self) -> None: ...
    def __enter__(self) -> ProfitClient: ...
    def __exit__(self, *exc) -> None: ...

    # Subscriptions
    def subscribe(self, ticker: str, *, exchange: str) -> None: ...
    def unsubscribe(self, ticker: str, *, exchange: str) -> None: ...

    # Event registration & event loop
    def on(self, event: Event) -> Callable: ...
    def run(self) -> None: ...
```

---

## Connection State Machine

`TStateCallback` reports connection status via 4 domains `(nConnStateType, nResult)`:

| Domain (`nConnStateType`) | Description | OK State (`nResult`) |
|---|---|---|
| `LOGIN (0)` | Authentication | `LOGIN_CONNECTED (0)` |
| `ROUTING (1)` | Order routing | `ROTEAMENTO_CONNECTED (2)` |
| `MARKET_DATA (2)` | Market data feed | `MARKET_CONNECTED (4)` |
⚠️ Degradation states handled with warnings:
- `MARKET_PERFORMANCE_WARNING (5)` — Server performance degradation warning.
- `MARKET_PARTIAL_CONNECTED (6)` — **Critical**: Server data stream active, but client callback processing stalled. Triggers critical logging and status notifications.

---

## Threading & Async Architecture

- **Synchronous Engine**: Thread-safe worker loop (`dispatcher thread` + `queue.Queue`).
- **Async Option**: Future async extensions (`AsyncProfitClient`) build on top of internal queues using `asyncio.loop.run_in_executor` and `asyncio.Queue` re-exports without modifying native `_bindings`.

---

## Native Binary Packaging Decisions

- Native proprietary DLL binaries (`ProfitDLL.dll` / `ProfitDLL64.dll`) remain external to PyPI wheels due to proprietary vendor licensing.
- Runtime loader resolves binary path from local project directories or environment variables (`PROFITDLL_PATH`).
- OS and architecture validation happens at runtime, raising helpful exceptions if binaries or platforms do not match.
