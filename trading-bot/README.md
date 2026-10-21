# Day-trading bot (Interactive Brokers: stocks + crypto)

A small, testable framework: **strategy → risk manager → engine → broker**.
It starts in **paper mode**, and every safety limit lives in code and config, not in prompts.

> ⚠️ Most retail day traders lose money. The included `ema_cross` strategy is a
> placeholder to exercise the plumbing. It is **not** a proven edge. Paper trade for weeks
> before considering real money, and never risk money you can't afford to lose.

## Setup steps

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
   .venv/bin/python -m pytest -q tests  # 24 tests, no IB connection needed
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
