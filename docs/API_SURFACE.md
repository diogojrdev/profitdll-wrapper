# API Surface — Function Inventory and Prioritization

Inventory of the **83 C functions exported** by ProfitDLL, organized by domain and implementation phase.

Priority Legend:
- **P0** — MVP Core (connect + subscribe + real-time trade streaming)
- **P1** — Full Market Data & Price Book Depth (v0.2)
- **P2** — Order Routing, Cancellations & Custody Positions (v0.3)
- **P3** — Historical Downloads, Corporate Actions & Accounts (v0.4)
- **P4** — Full Feature Coverage / V2 API extensions (v1.0)

---

## 1. Lifecycle and Configuration

| DLL Function | Priority | Signature (Summary) | Description / Notes |
|---|---|---|---|
| `DLLInitializeLogin` | **P0** | `(activation, user, pwd, 13 callbacks) → NL` | Full order routing mode |
| `DLLInitializeMarketLogin` | **P0** | `(activation, user, pwd, 8 callbacks) → NL` | Market data only mode |
| `DLLFinalize` | **P0** | `() → NL` | Clean shutdown and memory cleanup |
| `SetServerAndPort` | P1 | `(server, port) → NL` | Endpoint override |
| `GetServerClock` | P2 | `() → Double` | Server timestamp |
| `SetDayTrade` | P2 | `(bUseDayTrade: Integer) → NL` | Day-trade flag |
| `SetEnabledHistOrder` | P3 | `(bEnabled: Integer) → NL` | Automatic order history flag |
| `SetEnabledLogToDebug` | P3 | `(bEnabled: Integer) → NL` | Native debug logging flag |

---

## 2. Market Data Subscriptions

| DLL Function | Priority | Signature | Description / Notes |
|---|---|---|---|
| `SubscribeTicker` | **P0** | `(pwcTicker, pwcBolsa) → NL` | Real-time trade streaming |
| `UnsubscribeTicker` | **P0** | `(pwcTicker, pwcBolsa) → NL` | Unsubscribe trades |
| `SubscribePriceBook` | **P1** | `(pwcTicker, pwcBolsa) → NL` | Price book depth |
| `UnsubscribePriceBook` | **P1** | `(pwcTicker, pwcBolsa) → NL` | Unsubscribe price depth |
| `SubscribeOfferBook` | **P1** | `(pwcTicker, pwcBolsa) → NL` | V2 offer book stream |
| `UnsubscribeOfferBook` | **P1** | `(pwcTicker, pwcBolsa) → NL` | Unsubscribe offer book |
| `RequestTickerInfo` | P1 | `(pwcTicker, pwcBolsa) → NL` | Asset specification query |
| `SubscribeAdjustHistory` | P3 | `(...) → NL` | Corporate actions / dividend adjustments |
| `UnsubscribeAdjustHistory` | P3 | `(...) → NL` | Unsubscribe adjust history |

---

## 3. Native Callback Handlers (`Set*Callback`)

> In V1 initializations, callbacks are passed directly to `DLLInitialize*`. The `Set*` functions below update or replace callbacks dynamically.

### System & State

| DLL Function | Priority | Callback Signature |
|---|---|---|
| `SetStateCallback` | **P0** | `TStateCallback` (connection / login state) |
| `SetAssetListCallback` | P1 | `TAssetListCallback` |
| `SetAssetListInfoCallback` / `V2` | P1 | Asset info callbacks |
| `SetInvalidTickerCallback` | P1 | Invalid ticker notifications |
| `SetChangeCotationCallback` | P1 | Quote variation updates |
| `SetChangeStateTickerCallback` | P1 | Ticker trading state change |

### Market Data


| Função DLL | Prioridade | Tipo |
|---|---|---|
| `SetTradeCallback` / `V2` | **P0** (V1) / P4 (V2) | `TConnectorTradeCallback` (V2 precisa de `TranslateTrade`) |
| `SetHistoryTradeCallback` / `V2` | P3 | histórico de trades |
| `SetDailyCallback` | P1 | candle diário |
| `SetTheoreticalPriceCallback` | P2 | preço teórico |
| `SetTinyBookCallback` | P2 | tiny book |
| `SetSerieProgressCallback` | P3 | progresso de série |
| `SetOfferBookCallback` / `V2` | **P1** (V1) / P4 (V2) | book de ofertas |
| `SetPriceBookCallback` / `V2` | **P1** (V1) / P4 (V2) | book de preços |
| `SetAdjustHistoryCallback` / `V2` | P3 | ajustes |

### Ordens, contas e position

| Função DLL | Prioridade | Tipo |
|---|---|---|
| `SetAccountCallback` | P2 | info de conta |
| `SetHistoryCallback` / `V2` | P3 | histórico de ordens |
| `SetOrderChangeCallback` / `V2` | P2 | mudança de ordem |
| `SetOrderCallback` | P2 | callback de ordem |
| `SetOrderHistoryCallback` | P3 | histórico de ordens (novo) |
| `SetAssetPositionListCallback` | P2 | lista de position |

---

## 4. Ordens

| Função DLL | Prioridade | Assinatura (resumo) | Retorno |
|---|---|---|---|
| `SendBuyOrder` | P2 | `(conta, corr, senha, ticker, bolsa, price, qtd)` | `Int64` ProfitID |
| `SendSellOrder` | P2 | idem | ProfitID |
| `SendMarketBuyOrder` | P2 | `(…, qtd)` (sem price) | ProfitID |
| `SendMarketSellOrder` | P2 | idem | ProfitID |
| `SendStopBuyOrder` | P3 | `(…, price, stopPrice, qtd)` | ProfitID |
| `SendStopSellOrder` | P3 | idem | ProfitID |
| `SendChangeOrder` / `V2` | P3 | modifica ordem | ProfitID |
| `SendCancelOrder` / `V2` | P2 | cancela uma | NL |
| `SendCancelOrders` / `V2` | P3 | cancela várias | NL |
| `SendCancelAllOrders` / `V2` | P3 | cancela todas | NL |
| `SendZeroPosition` / `V2` | P3 | zera position | |
| `SendZeroPositionAtMarket` | P3 | zera a mercado | |
| `SendOrder` | P3 | genérico (struct `TConnectorSendOrder`) | unifica os Send* |

> V1 = structs antigas; **V2** = structs com `Int64` (corrige overflow de qtd/lote, 4.0.0.38). A lib prefere V2 quando disponível.

---

## 5. Consultas (accessor / request)

| Função DLL | Prioridade | Descrição |
|---|---|---|
| `GetOrders` | P2 | lista de ordens |
| `GetOrder` | P2 | ordem por ID |
| `GetOrderProfitID` | P2 | ProfitID de uma ordem |
| `GetOrderDetails` | P2 | detalhes da ordem |
| `GetPosition` / `V2` | P2 | position de um ativo |
| `GetHistoryTrades` | P3 | trades históricos |
| `GetLastDailyClose` | P3 | último fechamento diário |
| `GetAccounts` | P3 | lista de contas |
| `GetAccountDetails` | P3 | detalhes de conta |
| `GetSubAccountCount` | P3 | nº de sub-contas |
| `GetSubAccounts` | P3 | sub-contas |
| `HasOrdersInInterval` | P3 | ordens num intervalo |
| `EnumerateOrdersByInterval` | P3 | enumera ordens (callback) |
| `EnumerateAllOrders` | P3 | enumera todas (callback) |

---

## 6. Helpers e tradução

| Função DLL | Prioridade | Descrição |
|---|---|---|
| `TranslateTrade` | **P0** (indireto) | Traduz ponteiro opaco → `TConnectorTrade`. **Deve rodar dentro do callback** V2. |
| `GetAgentNameByID` | P3 | Nome do agente por ID (retorna `PWideChar` → liberar) |
| `GetAgentShortNameByID` | P3 | Abreviação |
| `GetAgentNameLength` | P3 | Tamanho do nome |
| `GetAgentName` | P3 | Nome (buffer fornecido) |

> Every function returning `PWideChar` requires manual deallocation — see memory management in `ARCHITECTURE.md`.

---

## Códigos de erro (`NL_*`) — tradução

Critical subset:

| Código | Hex | Significado | Tratamento sugerido |
|---|---|---|---|
| `NL_OK` | `0` | Sucesso | — |
| `NL_INTERNAL_ERROR` | `0x80000001` | Erro interno | `ProfitAPIError` |
| `NL_NOT_INITIALIZED` | `0x80000002` | Init não chamado | `RuntimeError` (bug do usuário) |
| `NL_INVALID_ARGS` | `0x80000003` | Args inválidos | `ValueError` |
| `NL_WAITING_SERVER` | `0x80000004` | Aguardando server | retry/warning |
| `NL_NO_LOGIN` | `0x80000005` | Sem login | `AuthError` |
| `NL_NO_LICENSE` | `0x80000006` | Sem licença | `LicenseError` |
| `NL_INVALID_TICKER` | `0x8000001F` | Ticker inválido | `ValueError` |
| `NL_HISTORY_PERIOD_LIMIT` | `0x8000002E` | Histórico > 30 dias | `ValueError` com dica |

Hierarquia proposta:

```
ProfitError
├── ProfitAPIError (código NL_*)
│   ├── AuthError          (login/senha/licença)
│   ├── InvalidArgumentError
│   └── ServerStateError
├── ProfitConnectionError
└── PlatformNotSupportedError
```

---

## Priorização visual (quantidade por fase)

```
P0 (MVP)        ████        ~6 funções  (init×2, finalize, sub/unsub ticker, TranslateTrade indireto)
P1 (v0.2)       ████████    ~12 funções (books, daily, info de ativos)
P2 (v0.3)       ██████████  ~16 funções (ordens básicas, positions)
P3 (v0.4)       ██████████████ ~22 funções (histórico, contas, V1 completo)
P4 (v1.0)       ████████    ~27 funções (todas as V2 + cobertura total)
                 ────────────────────────────────────────────
                              83 funções no total
```

**Estratégia:** nunca tentar bindar as 83 de uma vez. Cada fase fecha um **vertical funcional** testável de ponta a ponta (ex.: MVP = "consigo ver trades de PETR4 em tempo real").
