"""Bar-by-bar backtest using the same Strategy and RiskManager sizing as live.

Fills: entries at the signal bar's close plus slippage; stop/target checked on
following bars using high/low (stop assumed first when both are touched -
conservative). Fees charged per side.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bot.config import RiskConfig, Session
from bot.models import Action, Bar, Instrument, Market
from bot.risk import RiskManager
from bot.strategies.base import Strategy


@dataclass
class BtTrade:
    symbol: str
    entry_ts: datetime
    exit_ts: datetime
    qty: float
    entry: float
    exit: float
    pnl: float
    reason: str


def load_csv(path: str | Path) -> list[Bar]:
    """CSV with header: ts,open,high,low,close[,volume]; ts in ISO-8601 with offset."""
    with open(path, newline="") as f:
        return [Bar(datetime.fromisoformat(r["ts"]), float(r["open"]), float(r["high"]),
                    float(r["low"]), float(r["close"]), float(r.get("volume") or 0))
                for r in csv.DictReader(f)]


def save_csv(bars: list[Bar], path: str | Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.ts.isoformat(), b.open, b.high, b.low, b.close, b.volume])


def run_backtest(bars: list[Bar], inst: Instrument, strategy: Strategy, risk_cfg: RiskConfig,
                 equity: float = 10_000.0, session: Session | None = None) -> dict:
    risk = RiskManager(risk_cfg, state_file=None, pdt_guard=False)
    slip, fee = risk_cfg.slippage_pct / 100, risk_cfg.fee_pct / 100
    cash = equity
    curve = [equity]
    trades: list[BtTrade] = []
    pos = None  # (qty, entry, stop, target, ts)

    def close(i: int, price: float, reason: str):
        nonlocal cash, pos
        qty, entry, _, _, ts = pos
        px = price * (1 - slip)
        pnl = (px - entry) * qty - (entry + px) * qty * fee
        cash += pnl
        trades.append(BtTrade(inst.symbol, ts, bars[i].ts, qty, entry, px, pnl, reason))
        pos = None

    for i in range(strategy.warmup, len(bars)):
        b = bars[i]
        local = b.ts.astimezone(session.tz) if session else b.ts
        stock_session = session is not None and inst.market is Market.STOCKS
        if pos:
            _, _, stop, target, _ = pos
            if b.low <= stop:
                close(i, min(stop, b.open), "stop")
            elif target is not None and b.high >= target:
                close(i, max(target, b.open), "target")
            elif stock_session and local.time() >= session.flatten:
                close(i, b.close, "end of day")
            # Overnight gap guard: a stock position never survives a date change.
            elif stock_session and bars[i - 1].ts.astimezone(session.tz).date() != local.date():
                close(i, b.open, "session gap")
        sig = strategy.signal(bars[: i + 1], in_position=pos is not None)
        if sig and sig.action is Action.EXIT and pos:
            close(i, b.close, sig.reason or "strategy exit")
        elif sig and sig.action is Action.BUY and not pos:
            if stock_session and not (session.start <= local.time() < session.last_entry):
                pass
            else:
                entry = b.close * (1 + slip)
                qty = risk.size(inst, cash, entry, sig.stop)
                if qty > 0:
                    pos = (qty, entry, sig.stop, sig.target, b.ts)
        mark = cash + ((b.close - pos[1]) * pos[0] if pos else 0)
        curve.append(mark)
    if pos:
        close(len(bars) - 1, bars[-1].close, "end of data")
        curve.append(cash)

    return {"trades": trades, "equity_curve": curve, **metrics(trades, curve, equity)}


def metrics(trades: list[BtTrade], curve: list[float], start: float) -> dict:
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    peak, max_dd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak if peak else 0)
    rets = [(b - a) / a for a, b in zip(curve, curve[1:]) if a]
    mean = sum(rets) / len(rets) if rets else 0
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets)) if rets else 0
    return {
        "num_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) else None,
        "total_return_pct": round(100 * (curve[-1] - start) / start, 2),
        "max_drawdown_pct": round(100 * max_dd, 2),
        "sharpe_per_bar": round(mean / sd, 4) if sd else None,
        "avg_trade": round((sum(wins) + sum(losses)) / len(trades), 2) if trades else 0.0,
    }


def write_trades(trades: list[BtTrade], path: str | Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "entry_ts", "exit_ts", "qty", "entry", "exit", "pnl", "reason"])
        for t in trades:
            w.writerow([t.symbol, t.entry_ts.isoformat(), t.exit_ts.isoformat(), t.qty,
                        round(t.entry, 4), round(t.exit, 4), round(t.pnl, 2), t.reason])
