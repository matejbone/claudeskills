# Trading bot (Interactive Brokers): daily trend following + intraday

A small, testable framework: **strategy → risk manager → engine → broker**.
It starts in **paper mode**, and every safety limit lives in code and config, not in prompts.

> ⚠️ Most retail day traders lose money. The included `ema_cross` strategy is a
> placeholder to exercise the plumbing. It is **not** a proven edge. Paper trade for weeks
> before considering real money, and never risk money you can't afford to lose.

## Two modes

| | **Trend following** (recommended) | Intraday (original) |
|---|---|---|
| Command | `python -m bot trend-run --config trend.yaml` | `python -m bot run --config config.yaml` |
| Markets | Forex majors + UCITS ETFs (S&P 500, Europe 600, gold, euro govt bonds) | Crypto (and US stocks) |
| Decisions | Once a day at 09:30 CET | Every bar |
| Holding period | Days to weeks, **held overnight** | Minutes to hours, flat by 15:55 |
| Trades | Roughly 10–40 a year per asset | Many per day |
| Evidence | Time-series momentum across dozens of markets over decades (Moskowitz, Ooi & Pedersen 2012) | None that survives IB crypto fees |

### Trend following: how it works
- **Signal:** for each asset, check whether the price is higher or lower than it was 1, 3, 6 and 12 months ago. All up gives +1 (long), all down gives −1 (short), and mixed results give something in between. ETFs are long-only, so they go flat in a downtrend. Forex can be long or short.
- **Size:** each asset is scaled so it contributes similar risk. Calm markets get bigger positions, wild ones smaller. The whole portfolio targets about **8% yearly volatility**.
- **Caps:** at most 50% of equity per asset and 150% gross across all assets. Trades only happen when a position is more than 25% off target, which keeps fees low.
- **Max drawdown halt:** if equity falls 20% from its peak, the bot sells everything and **refuses to restart** until you review the journal and delete `trend_state.json`.
- **Working hours:** starts at 08:00 and rebalances at 09:30 (after Xetra opens). At 15:55 the program exits but **positions stay open**, because holding through trends is the strategy. There are no stop-losses. Risk is controlled by position size, the caps and the drawdown halt.
- **Missing data:** if an asset's data can't be fetched, it's left untouched for the day rather than sold.

**What to expect:** trend following loses on most small moves and in choppy, sideways years, sometimes for a year or more. Its gains come from a few big trends, and historically it helped most during prolonged crashes. Expect long flat or losing stretches, not steady income.

### Trend following: steps
1. Complete IBKR setup steps 1–3 below (paper account, TWS/IB Gateway, API on).
   - Forex short positions need a **margin** account. EU retail clients can only buy **UCITS** ETFs, not US-listed ones, so the example uses Xetra listings.
   - Subscribe to Xetra/German ETF market data and IDEALPRO forex data.
2. Run `cp trend.example.yaml trend.yaml`. Check each ETF symbol resolves in TWS.
3. Download about 10 years of daily data: `.venv/bin/python -m bot trend-download --years 10`
4. Backtest: `.venv/bin/python -m bot trend-backtest --curve-out data/curve.csv`. This reports CAGR, volatility, Sharpe, max drawdown, trades per year, fees paid and returns per year. Ask Claude to review the results with the `backtest-expert` skill.
5. Paper trade with `.venv/bin/python -m bot trend-run` for at least **2–3 months**. A trend strategy needs time to show anything.
6. Only then decide about live trading (same three switches as below).

## Setup steps (IBKR, shared by both modes)

1. **Open an IBKR account** and, in Client Portal, enable **paper trading**. You get a separate
   `DU…` paper account. For crypto, request crypto trading permissions; it's offered via PAXOS
   in supported regions only, so check yours.
2. **Market data.** Subscribe to US stock data (e.g. "US Securities Snapshot and Futures Value
   Bundle") or IB returns delayed or no bars.
3. **Install TWS or IB Gateway** and log in to the **paper** account.
   In *Configure → API → Settings*: enable "ActiveX and Socket Clients", leave "Read-Only API"
   **off** for paper, and note the port (TWS paper `7497`, Gateway paper `4002`).
4. **Install the bot:**
   ```bash
   cd trading-bot
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cp config.example.yaml config.yaml   # edit symbols, risk limits, strategy params
   .venv/bin/python -m pytest -q tests  # 42 tests, no IB connection needed
   ```
5. **Get data and backtest:**
   ```bash
   .venv/bin/python -m bot download --symbol SPY --out data/SPY_5m.csv
   .venv/bin/python -m bot backtest --csv data/SPY_5m.csv --symbol SPY --trades-out data/SPY_trades.csv
   ```
   IB only serves a limited history per request (the downloader asks for 5 days of stocks and
   2 days of crypto). Use longer data from another source in the same CSV format
   (`ts,open,high,low,close,volume`) for serious tests. Then ask Claude to review the result
   with the `backtest-expert` skill (overfitting, sample size, costs).
6. **Paper trade:** `.venv/bin/python -m bot run`. Leave it for **2–4 weeks**, then compare
   `journal.csv` against the backtest.
7. **Live (optional, your decision):** set `mode: live`, use the live port (`7496`/`4001`),
   log TWS into the live account, start with the smallest size, and export
   `TRADING_BOT_LIVE=yes`. Without all three, the bot refuses to start.

## Safety features

| Guard | Where |
|---|---|
| Paper by default. Live needs `mode: live` **and** a live port **and** `TRADING_BOT_LIVE=yes` | `bot/config.py` |
| Refuses a real (non-`DU`) account in paper mode, and a paper account in live mode | `Engine.preflight` |
| Risk per trade capped at 5% max (default 0.5%), position size cap, minimum stop distance | `bot/risk.py` |
| **Daily loss circuit breaker:** flattens everything and blocks entries for the rest of the day (persists across restarts) | `RiskManager.update_equity` |
| Max open positions, max trades per day | `RiskManager.can_open` |
| **PDT guard:** under $25k, no 4th stock day trade in 5 business days | `RiskManager.can_open` |
| Stocks: no entries before 09:45 / after 15:30 ET, flattened at 15:50 ET (no overnight holds) | `Engine._stock_window` |
| Stocks: broker-side bracket (stop + target) survives a bot crash | `IBBroker.open_long` |
| **Working hours:** no new trades outside `start`–`last_entry`; at `stop` closes every position it opened and exits (retries partial fills, then warns `STOP_NOT_FLAT` in the journal) | `Engine._operating_window` |
| **Kill switch:** create a file named `STOP` next to the config to flatten all and exit | `Engine.step` |
| Leaves positions it didn't open alone | `Engine.preflight` |
| Every action logged to `journal.csv` | `bot/journal.py` |

**Known limits:**
- Crypto on IB has no broker-side stop orders, so the bot enforces crypto stops itself. If the bot isn't running, crypto positions are **unprotected**.
- Stock bracket legs are DAY orders. If the bot dies before 15:50 ET, the position can be held overnight without a stop.
- Order types (IOC brackets, PAXOS IOC limits) are written against IB's docs but **haven't been verified against a live TWS session yet**. Watch the first paper sessions closely.

## Running during working hours (default: crypto only, CET)

`config.example.yaml` is set up for Central Europe: **BTC and ETH only, Mon–Fri**. Times are
Europe/Berlin, and summer/winter time is handled automatically.

| Time | What the bot does |
|---|---|
| before 08:00 | connected, waits, no trades |
| 08:00 – 15:30 | trades normally |
| 15:30 – 15:55 | manages open trades (stops, targets, exits), opens nothing new |
| 15:55 | sells everything it opened and exits |
| Sat / Sun | exits immediately |

US stocks are disabled because they trade 15:30–22:00 CET, outside these hours. Crypto
trades 24/7, so closing out at 15:55 means nothing is left open while you're away. On IB,
crypto has no broker-side stop.

**Daily routine:**
1. Log IB Gateway into the paper account.
2. Start `.venv/bin/python -m bot run`. You can schedule this for 07:55 with Windows Task
   Scheduler, or with launchd or cron on Mac/Linux.
3. Keep the computer awake. Turn off sleep, and on a laptop keep it plugged in.
4. Glance at `journal.csv`. Create a file called `STOP` to shut it down early.

To change the times, edit `operating_hours`. To run around the clock, delete that block.

## Adding your own strategy

1. Create `bot/strategies/my_strategy.py` with a subclass of `Strategy` that implements
   `warmup` and `signal(bars, in_position)`. Return `Signal(Action.BUY, stop=…, target=…)`
   or `Signal(Action.EXIT)`.
2. Register it in `bot/strategies/__init__.py` and set `strategy.name` in `config.yaml`.
3. Backtest it, then paper trade it. The engine, risk limits and broker code stay unchanged.

Strategies are long-only in this version.
