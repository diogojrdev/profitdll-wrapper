<div align="center">

# profitdll-wrapper

Wrapper Python de alta performance, idiomático, tipado e memory-safe para o **ProfitDLL** (API nativa da Nelogica).

[![PyPI](https://img.shields.io/pypi/v/profitdll-wrapper.svg?cacheSeconds=3600)](https://pypi.org/project/profitdll-wrapper)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue.svg)](https://www.python.org)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://docs.astral.sh/ruff)
[![Type Checking: mypy](https://img.shields.io/badge/mypy-strict-blue.svg)](https://mypy.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-v0.4.0-blue.svg)](#status)

[English](README.md) | **Português (BR)**

</div>

---

> [!NOTE]
> **Status: v0.4.0 — P0 (Trades), P1 (Price Depth), P2 (Roteamento de Ordens & Custódia) e a stack de ingestão histórica validados contra o simulador/DLL real.**
> Suíte completa com 225 testes unitários e de contrato ABI (80%+ de cobertura), rodando sob `mypy --strict`, `ruff` e `pytest`. Arquitetura *Pure Enqueue* imune a crashes de reentrância C ↔ GIL.

---

> [!WARNING]
> **Projeto independente, mantido pela comunidade — sem afiliação com a Nelogica.**
> O `profitdll-wrapper` é desenvolvido e mantido pela comunidade. Profit,
> ProfitDLL e nomes relacionados são produtos e marcas da Nelogica, que
> não endossa, patrocina nem apoia este projeto. A DLL proprietária
> não é distribuída aqui.
>
> **Sem responsabilidade financeira.** Este software pode enviar ordens reais com
> dinheiro real quando conectado a uma conta de corretora real. É fornecido "no estado
> em que se encontra", sem qualquer garantia, para fins de pesquisa e educação. Os autores
> **não aceitam responsabilidade por perdas financeiras, ordens perdidas, duplicadas,
> incorretas ou atrasadas, dados incorretos ou qualquer resultado de trading**. Valide
> tudo primeiro em uma conta simulador/demo — você é o único responsável pelas ordens
> que o seu código envia.

---

## O que é o `profitdll-wrapper`

`profitdll-wrapper` é um wrapper Python moderno para o ProfitDLL da Nelogica — uma API nativa em C/Pascal (convenção de chamada `stdcall`, com ponteiros de memória brutos e threads de callback em um `ConnectorThread` C dedicado).

Ele abstrai a complexidade de baixo nível do ctypes e fornece:
- **API idiomática**: context managers (`with`), dataclasses imutáveis (`Trade`, `PriceLevel`, `PriceBookSnapshot`, `DailyCandle`, `Order`, `Position`, `Account`), tipos `enum` estritos e type hints completos;
- **Roteamento de Ordens & Custódia**: ordens limitadas (`send_buy_order`, `send_sell_order`), ordens a mercado (`send_market_buy`, `send_market_sell`), cancelamentos (`cancel_order`, `cancel_all_orders`) e rastreamento em tempo real de posições em custódia (`get_position`, `Event.ORDER`, `Event.POSITION`);
- **Arquitetura Pure Enqueue**: os callbacks C apenas enfileiram payloads posicionais leves em microssegundos, sem chamadas reentrantes ao ctypes, prevenindo deadlocks e segfaults em alto volume de mercado;
- **Tolerância a falhas e segurança**: o isolamento de exceções do usuário nos handlers de eventos garante que falhas de callback nunca crashem o processo da DLL nativa nem interrompam os streams de dados;
- **Zero dependências em runtime**: construído estritamente com a biblioteca padrão do Python (`dependencies = []`).

A documentação detalhada de arquitetura e API (em inglês) está publicada em <https://diogojrdev.github.io/profitdll-wrapper/>:

| Documento | Conteúdo |
|---|---|
| [Architecture](https://diogojrdev.github.io/profitdll-wrapper/ARCHITECTURE/) | Design em camadas, padrões de abstração e invariantes de thread-safety |
| [API Surface](https://diogojrdev.github.io/profitdll-wrapper/API_SURFACE/) | Mapeamento das funções nativas do ProfitDLL e auditoria de ABI |
| [Ingest](https://diogojrdev.github.io/profitdll-wrapper/INGEST/) | Ingestão de dados históricos: sinks, schema e a CLI `profitdll-ingest` |

---

## Instalação

Instale do [PyPI](https://pypi.org/project/profitdll-wrapper) com pip:

```bash
pip install profitdll-wrapper
```

Ou, em um projeto gerenciado com [uv](https://docs.astral.sh/uv):

```bash
uv add profitdll-wrapper
```

> [!TIP]
> O nome da distribuição é `profitdll-wrapper` (com hífen), mas o nome de import
> é `profitdll_wrapper` (com underscore):
> ```python
> from profitdll_wrapper import Event, ProfitClient
> ```

**Requisitos:** Python 3.10+ no **Windows** (o ProfitDLL nativo é uma biblioteca Windows `stdcall`).

### Extras opcionais

O pacote principal tem zero dependências em runtime. Os backends de ingest são opt-in:

```bash
pip install "profitdll-wrapper[postgres]"   # sink PostgreSQL / TimescaleDB (psycopg)
pip install "profitdll-wrapper[parquet]"    # sink Parquet (duckdb)
pip install "profitdll-wrapper[all]"        # tudo
```

### A DLL nativa (proprietária)

O ProfitDLL da Nelogica é proprietário e **não** vem embutido neste pacote.
Para conectar aos servidores ou ao simulador da Nelogica:
1. Defina a variável de ambiente `PROFITDLL_PATH=/caminho/para/ProfitDLL.dll` (ou `ProfitDLL64.dll`), ou;
2. Coloque a DLL dentro de um diretório `dll/` no seu diretório de trabalho.
3. Crie um arquivo `.env` no seu diretório de trabalho com as credenciais do simulador:
   ```env
   ACTIVATION_KEY=sua_chave
   USER=seu_usuario
   PASSWORD=sua_senha
   ```

O diretório da DLL também precisa conter os dados de runtime do fornecedor (arquivos de roteamento das corretoras); mantenha-o fora do controle de versão.

---

## Início rápido

### 1. Ticks de trades em tempo real (P0)

```python
from profitdll_wrapper import Event, ProfitClient, Trade

with ProfitClient(
    activation_key="KEY...",
    user="USER...",
    password="PASSWORD...",
    mode="market_data",  # "market_data" ou "routing"
    # broker_id=15003,   # opcional; o padrão é a BROKER do arquivo .env
) as client:
    client.subscribe("WDOFUT", exchange="F")

    @client.on(Event.TRADE)
    def on_trade(trade: Trade) -> None:
        print(
            f"{trade.asset.ticker} | Preço: {trade.price:.2f} x{trade.quantity} | Agressor: {trade.trade_type}"
        )

    client.run()  # bloqueia mantendo o loop de eventos ativo (Ctrl+C para sair)
```

### 2. Book de ofertas / profundidade e consultas thread-safe (P1)

```python
from profitdll_wrapper import Event, PriceLevel, ProfitClient

with ProfitClient(
    activation_key="KEY...",
    user="USER...",
    password="PASSWORD...",
    mode="market_data",
) as client:
    client.subscribe_price_depth("PETR4", exchange="B")

    @client.on(Event.PRICE_LEVEL)
    def on_level(level: PriceLevel) -> None:
        print(
            f"[{level.update_type.name}] {level.side.name} pos={level.position} qty={level.quantity}"
        )

    # Consulta de nível thread-safe fora do callback
    # top_buy = client.get_price_group("PETR4", side=0, position=0, exchange="B")

    client.run()
```

---

## Exemplos práticos

Explore o diretório [`examples/`](examples/) — onze scripts prontos para rodar, do streaming de market data a bots de trading:

| Script | Categoria | Descrição | Modo |
|---|---|---|---|
| [`01_subscribe_ticker.py`](examples/01_subscribe_ticker.py) | MVP / Cotações | Streaming mínimo de ticks de trades em tempo real | `market_data` |
| [`02_price_depth.py`](examples/02_price_depth.py) | Price Book | Atualizações de profundidade do book e snapshots | `market_data` |
| [`03_live_smoke.py`](examples/03_live_smoke.py) | Smoke Test | Validação live autônoma com relatório | `market_data` / `routing` |
| [`04_send_order.py`](examples/04_send_order.py) | Roteamento | Ordens limitadas de compra/venda e rastreamento de execuções | `routing` |
| [`05_market_data_streamer.py`](examples/05_market_data_streamer.py) | Data Streamer | Trades, book V2 e preços de fechamento → CSV / pandas DataFrame | `market_data` |
| [`06_trading_bot_sample.py`](examples/06_trading_bot_sample.py) | Trading Bot | Blueprint completo de bot: máquina de estados, order manager, Stop Loss & Take Profit | `routing` |
| [`07_watchdog_and_reconciliation.py`](examples/07_watchdog_and_reconciliation.py) | Infra / Reconciliação | Watchdog de saúde da DLL, reconexão automática e reconciliação diária de posições | `routing` |
| [`08_corporate_actions_and_history.py`](examples/08_corporate_actions_and_history.py) | Histórico & Eventos corporativos | Download de histórico tick a tick e eventos corporativos | `market_data` |
| [`09_historical_to_database.py`](examples/09_historical_to_database.py) | Histórico → Banco de dados | Trades históricos para SQLite via subpacote `ingest` | `market_data` |
| [`10_times_and_trades_tui.py`](examples/10_times_and_trades_tui.py) | TUI / Market Data | Times & Trades com barra de resumo nativa, fita espelhada comprador/vendedor, barras de volume e medidor de pressão (`rich`, `--demo` em qualquer OS) | `market_data` |
| [`11_order_book_tui.py`](examples/11_order_book_tui.py) | TUI / Market Data | Livro de ofertas completo (DOM L2) com barra de resumo nativa, lados Compra/Venda espelhados e barras de volume proporcionais (`rich`, `--demo` em qualquer OS) | `market_data` |

---

## Dados históricos → Banco de dados

O comando `profitdll-ingest` baixa trades históricos tick a tick (e candles diários opcionais) via ProfitDLL e os persiste em um backend configurável. SQLite e CSV são embutidos (zero dependências extras); Parquet e PostgreSQL/TimescaleDB vêm como extras opcionais.

### Início rápido (SQLite, zero deps)

```bash
pip install profitdll-wrapper
profitdll-ingest --ticker VALE3 --start 01/01/2026 --end 31/01/2026
# -> escreve em ./profit_data.db
```

### PostgreSQL / TimescaleDB via Docker

O banco de dados roda no Docker; o script de ingestão roda no host Windows (onde está a DLL nativa). Pegue o `docker-compose.yml` e o `.env.example` do repositório.

```bash
cp .env.example .env             # defina TIMESCALE_PASSWORD
docker compose up -d timescaledb
pip install "profitdll-wrapper[postgres]"
profitdll-ingest --ticker VALE3,PETR4 --exchange B,B \
    --start 01/01/2026 --end 31/01/2026 \
    --to postgres \
    --db-url postgresql://profit:secret@localhost:5432/profit
```

### API programática

```python
from profitdll_wrapper import ProfitClient
from profitdll_wrapper.ingest import create_sink, ingest_history

sink = create_sink("sqlite", db_url="profit.db")
with ProfitClient(activation_key="...", user="...", password="...", mode="market_data") as client:
    stats = ingest_history(
        client=client,
        sink=sink,
        tickers=[("VALE3", "B")],
        start_date="01/01/2026 09:00:00",
        end_date="31/01/2026 18:00:00",
    )
print(f"{stats.trades_written} trades persistidos em {stats.elapsed_seconds:.1f}s")
sink.close()
```

Veja o [guia de ingestão](https://diogojrdev.github.io/profitdll-wrapper/INGEST/) (em inglês) para detalhes de schema, hypertables, idempotência e tuning, e [`examples/09_historical_to_database.py`](examples/09_historical_to_database.py) para um exemplo ponta a ponta executável.

---

## Desenvolvimento e testes

Este projeto usa [uv](https://docs.astral.sh/uv) para gestão de dependências e tooling.

```bash
git clone https://github.com/diogojrdev/profitdll-wrapper.git
cd profitdll-wrapper
uv sync                                  # cria o virtualenv e instala as dependências de dev
uv run pytest                            # roda a suíte completa (225 testes unitários e de ABI)
uv run ruff check .                      # roda o linter
uv run ruff format --check .             # checa a formatação do código
uv run mypy --strict src                 # checa as anotações de tipo em modo strict
```

### Testes de integração com a DLL nativa real

Os testes de integração que rodam contra a DLL real da Nelogica e o simulador usam o marcador `@pytest.mark.integration`:

```bash
uv run pytest -m integration
```

---

## Feedback

Se este projeto te ajuda a operar na B3, considere dar uma ⭐ e [abrir uma issue](https://github.com/diogojrdev/profitdll-wrapper/issues/new/choose) com o seu feedback — issues nesta fase inicial são ouro para priorizar a roadmap.

---

## Licença

[MIT](LICENSE). O ProfitDLL nativo da Nelogica é software proprietário e não está incluído neste repositório.

Este é um projeto independente, mantido pela comunidade, sem afiliação com a Nelogica, fornecido **sem responsabilidade financeira** por perdas de trading — veja o aviso legal no topo.

## Contribuindo

Contribuições são bem-vindas! Veja [`CONTRIBUTING.md`](CONTRIBUTING.md) (em inglês) para as diretrizes de desenvolvimento.
