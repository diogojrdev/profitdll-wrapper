# API Surface — Function Inventory & Mapping

Inventory of the **83 native C functions exported** by ProfitDLL, organized by domain and implementation status.

Priority & Status:
- **P0** — Core lifecycle & real-time trade streaming (Implemented)
- **P1** — Market data & price book depth (Implemented)
- **P2** — Order routing, cancellations & custody positions (Implemented)
- **P3** — Historical downloads, corporate actions & accounts (Implemented)
- **P4** — Future extensions and remaining V2 functions

---

## 1. Lifecycle and Configuration

| DLL Function | Priority | Signature (Summary) | Description / Notes |
|---|---|---|---|
| `DLLInitializeLogin` | **P0** | `(activation, user, pwd, 13 callbacks) → NL` | Full order routing initialization |
| `DLLInitializeMarketLogin` | **P0** | `(activation, user, pwd, 8 callbacks) → NL` | Market data only initialization |
| `DLLFinalize` | **P0** | `() → NL` | Clean shutdown and memory cleanup |
| `SetServerAndPort` | P1 | `(server, port) → NL` | Endpoint override |
| `GetServerClock` | P2 | `() → Double` | Server timestamp |
| `SetDayTrade` | P2 | `(bUseDayTrade: Integer) → NL` | Day-trade routing flag |
| `SetEnabledHistOrder` | P3 | `(bEnabled: Integer) → NL` | Automatic order history download flag |
| `SetEnabledLogToDebug` | P3 | `(bEnabled: Integer) → NL` | Native debug logging flag |

---

## 2. Market Data Subscriptions

| DLL Function | Priority | Signature | Description / Notes |
|---|---|---|---|
| `SubscribeTicker` | **P0** | `(pwcTicker, pwcBolsa) → NL` | Real-time trade streaming |
| `UnsubscribeTicker` | **P0** | `(pwcTicker, pwcBolsa) → NL` | Unsubscribe trades |
| `SubscribePriceBook` | **P1** | `(pwcTicker, pwcBolsa) → NL` | Price book depth stream |
| `UnsubscribePriceBook` | **P1** | `(pwcTicker, pwcBolsa) → NL` | Unsubscribe price depth |
| `SubscribeOfferBook` | **P1** | `(pwcTicker, pwcBolsa) → NL` | V2 offer book stream |
| `UnsubscribeOfferBook` | **P1** | `(pwcTicker, pwcBolsa) → NL` | Unsubscribe offer book |
| `RequestTickerInfo` | P1 | `(pwcTicker, pwcBolsa) → NL` | Asset specification query |
| `SubscribeAdjustHistory` | P3 | `(...) → NL` | Corporate actions / dividend adjustments |
| `UnsubscribeAdjustHistory` | P3 | `(...) → NL` | Unsubscribe adjust history |

---

## 3. Native Callback Handlers (`Set*Callback`)

> In V1 initializations, initial callbacks are supplied to `DLLInitialize*`. The `Set*` functions configure or override callbacks dynamically.

### System & State

| DLL Function | Priority | Callback Signature | Description |
|---|---|---|---|
| `SetStateCallback` | **P0** | `TStateCallback` | Connection & login state changes |
| `SetAssetListCallback` | P1 | `TAssetListCallback` | Full asset catalog enumeration |
| `SetAssetListInfoCallback` / `V2` | P1 | `TAssetListInfoCallback` | Asset metadata callbacks |
| `SetInvalidTickerCallback` | P1 | `TInvalidTickerCallback` | Notifications for unknown tickers |
| `SetChangeCotationCallback` | P1 | `TChangeCotationCallback` | Quote variation updates |
| `SetChangeStateTickerCallback` | P1 | `TChangeStateTickerCallback` | Ticker trading state / auction changes |

### Market Data

| DLL Function | Priority | Callback Signature | Description |
|---|---|---|---|
| `SetTradeCallback` / `V2` | **P0** | `TConnectorTradeCallback` | Real-time trade stream (V2 uses `TranslateTrade`) |
| `SetHistoryTradeCallback` / `V2` | P3 | `THistoryTradeCallback` | Historical trade stream |
| `SetDailyCallback` | P1 | `TDailyCallback` | Daily candle data |
| `SetTheoreticalPriceCallback` | P2 | `TTheoreticalPriceCallback` | Auction theoretical pricing |
| `SetTinyBookCallback` | P2 | `TTinyBookCallback` | Top of book updates |
| `SetSerieProgressCallback` | **P3** | `TProgressCallback` | Historical request progress (0–100%) |
| `SetOfferBookCallback` / `V2` | **P1** | `TOfferBookCallback` | Offer book (L2) updates |
| `SetPriceBookCallback` / `V2` | **P1** | `TPriceBookCallback` | Price depth aggregation |
| `SetAdjustHistoryCallback` / `V2` | P3 | `TAdjustHistoryCallback` | Corporate actions adjustments |

### Orders, Accounts & Custody

| DLL Function | Priority | Callback Signature | Description |
|---|---|---|---|
| `SetAccountCallback` | P2 | `TAccountCallback` | Account details & roster delivery |
| `SetHistoryCallback` / `V2` | P3 | `THistoryCallback` | Order history stream |
| `SetOrderChangeCallback` / `V2` | P2 | `TOrderChangeCallback` | Order lifecycle and fill updates |
| `SetOrderCallback` | P2 | `TOrderCallback` | General order event notifications |
| `SetOrderHistoryCallback` | P3 | `TOrderHistoryCallback` | Historical order query responses |
| `SetAssetPositionListCallback` | P2 | `TAssetPositionListCallback` | Custody position updates |

---

## 4. Order Routing

| DLL Function | Priority | Signature (Summary) | Return Type | Description |
|---|---|---|---|---|
| `SendBuyOrder` | P2 | `(account, broker, pwd, ticker, exchange, price, qty)` | `Int64` | Submits limit buy order |
| `SendSellOrder` | P2 | `(account, broker, pwd, ticker, exchange, price, qty)` | `Int64` | Submits limit sell order |
| `SendMarketBuyOrder` | P2 | `(account, broker, pwd, ticker, exchange, qty)` | `Int64` | Submits market buy order |
| `SendMarketSellOrder` | P2 | `(account, broker, pwd, ticker, exchange, qty)` | `Int64` | Submits market sell order |
| `SendStopBuyOrder` | P3 | `(account, broker, pwd, ticker, exchange, price, stopPrice, qty)` | `Int64` | Submits stop-buy order |
| `SendStopSellOrder` | P3 | `(account, broker, pwd, ticker, exchange, price, stopPrice, qty)` | `Int64` | Submits stop-sell order |
| `SendChangeOrder` / `V2` | P3 | Modifies price / quantity | `Int64` | Modifies active order |
| `SendCancelOrder` / `V2` | P2 | Single order cancellation | `NL` | Cancels single order |
| `SendCancelOrders` / `V2` | P3 | Multiple order cancellation | `NL` | Cancels order batch |
| `SendCancelAllOrders` / `V2` | P3 | Account cancellation | `NL` | Cancels all open orders |
| `SendZeroPosition` / `V2` | P3 | Position liquidation | `NL` | Closes asset position |
| `SendZeroPositionAtMarket` | P3 | Market liquidation | `NL` | Closes position at market |
| `SendOrder` | P3 | `(TConnectorSendOrder struct)` | `Int64` | Unified order submission |

> **V1 vs V2 Structs:** V1 structs use 32-bit fields; V2 structs use 64-bit integers (`Int64`) to prevent overflow in quantity and lot fields. The wrapper automatically selects V2 structs when available.

---

## 5. Queries & Accessors

| DLL Function | Priority | Description |
|---|---|---|
| `GetOrders` | P2 | Roster of active orders |
| `GetOrder` | P2 | Query order by local ID |
| `GetOrderProfitID` | P2 | Resolve native ProfitID for an order |
| `GetOrderDetails` | P2 | Query detailed order record |
| `GetPosition` / `V2` | P2 | Query custody position for an asset |
| `GetHistoryTrades` | P3 | Asynchronous historical trade request |
| `GetLastDailyClose` | P3 | Query last daily close price |
| `GetAccounts` | P3 | Query trading accounts roster |
| `GetAccountDetails` | P3 | Query account details |
| `GetSubAccountCount` | P3 | Sub-account count |
| `GetSubAccounts` | P3 | Query sub-account list |
| `HasOrdersInInterval` | P3 | Check for orders within time range |
| `EnumerateOrdersByInterval` | P3 | Enumerate orders via callback in range |
| `EnumerateAllOrders` | P3 | Enumerate all orders via callback |

---

## 6. Helpers & Memory Management

| DLL Function | Priority | Description |
|---|---|---|
| `TranslateTrade` | **P0** | Decodes opaque pointer to `TConnectorTrade`. Must execute synchronously within the callback. |
| `GetAgentNameByID` | P3 | Broker name by ID (returns heap-allocated `PWideChar` requiring `DLLFreeMemory`). |
| `GetAgentShortNameByID` | P3 | Broker abbreviation by ID |
| `GetAgentNameLength` | P3 | String length of broker name |
| `GetAgentName` | P3 | Broker name copied into caller-allocated buffer |

---

## 7. Error Codes (`NL_*`)

Critical error codes returned by the native DLL and their Python exception mappings:

| Code | Hex | Description | Python Exception |
|---|---|---|---|
| `NL_OK` | `0` | Success | None (normal return) |
| `NL_INTERNAL_ERROR` | `0x80000001` | Internal DLL error | `ProfitAPIError` |
| `NL_NOT_INITIALIZED` | `0x80000002` | Lifecycle not initialized | `RuntimeError` |
| `NL_INVALID_ARGS` | `0x80000003` | Invalid argument(s) | `InvalidArgumentError` / `ValueError` |
| `NL_WAITING_SERVER` | `0x80000004` | Waiting for server response | Retried or warning logged |
| `NL_NO_LOGIN` | `0x80000005` | Invalid login / credentials | `AuthError` |
| `NL_NO_LICENSE` | `0x80000006` | Missing or invalid license | `LicenseError` |
| `NL_INVALID_TICKER` | `0x8000001F` | Unknown or invalid ticker | `ValueError` / skipped |
| `NL_HISTORY_PERIOD_LIMIT` | `0x8000002E` | History request > 30 days | `HistoryPeriodLimitError` |

### Exception Hierarchy

```
ProfitError
├── ProfitAPIError (NL_* error codes)
│   ├── AuthError (login / license rejection)
│   ├── InvalidArgumentError
│   │   └── HistoryPeriodLimitError (start date > 30 days)
│   └── ServerStateError
├── ProfitConnectionError
└── PlatformNotSupportedError
```
