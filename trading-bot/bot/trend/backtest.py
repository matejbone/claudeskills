"""Daily portfolio backtest for the trend strategy.

Signals use closes up to day t; the resulting weights earn day t+1's return
(no look-ahead). Trades follow the same threshold rule as live and pay each
asset's cost_pct on the traded notional. Prices from different calendars are
forward-filled onto a common set of dates.
"""
from __future__ import annotations

import math
from datetime import date

from bot.models import Bar
from bot.trend.config import TrendConfig
from bot.trend.signal import TRADING_DAYS, realized_vol, target_weights, trend_signal


def run_trend_backtest(data: dict[str, list[Bar]], cfg: TrendConfig, start_equity: float = 10_000) -> dict:
    assets = {a.inst.symbol: a for a in cfg.assets if a.inst.symbol in data}
    if not assets:
        raise ValueError("no data for any configured asset")
    by_sym = {s: {b.ts.date(): b.close for b in data[s]} for s in assets}
    dates = sorted(set().union(*by_sym.values()))

    hist: dict[str, list[float]] = {s: [] for s in assets}
    last: dict[str, float | None] = {s: None for s in assets}
    w = {s: 0.0 for s in assets}
    equity, peak, max_dd = start_equity, start_equity, 0.0
    curve: list[tuple[date, float]] = []
    trades, cost_total, gross_sum = 0, 0.0, 0.0

    for i, d in enumerate(dates):
        # 1) apply today's returns to yesterday's weights
        rets = {}
        for s in assets:
            px = by_sym[s].get(d)
            if px is not None:
                rets[s] = px / last[s] - 1 if last[s] else 0.0
                last[s] = px
                hist[s].append(px)
            else:
                rets[s] = 0.0
        port_r = sum(w[s] * rets[s] for s in assets)
        equity *= 1 + port_r
        if 1 + port_r > 0:
            w = {s: w[s] * (1 + rets[s]) / (1 + port_r) for s in assets}

        # 2) rebalance at today's close (only on weekdays, like the live bot)
        if d.weekday() < 5:
            sigs, vols = {}, {}
            for s in assets:
                if hist[s]:
                    sig = trend_signal(hist[s], cfg.lookbacks)
                    sigs[s] = sig if sig is not None else 0.0
                    vols[s] = realized_vol(hist[s], cfg.vol_window) or 0.0
            tw = target_weights(sigs, vols, target_vol_pct=cfg.target_vol_pct,
                                max_weight=cfg.max_weight, max_gross=cfg.max_gross,
                                long_only=cfg.long_only)
            for s, target in tw.items():
                cur = w[s]
                delta = target - cur
                if delta == 0:
                    continue
                closing = target == 0 or (cur != 0 and (target > 0) != (cur > 0))
                big = abs(delta) >= cfg.rebalance_threshold * max(abs(target), abs(cur))
                if closing or (big and abs(delta) * equity >= assets[s].min_order):
                    cost = abs(delta) * equity * assets[s].cost_pct / 100
                    equity -= cost
                    cost_total += cost
                    w[s] = target
                    trades += 1
        gross_sum += sum(abs(v) for v in w.values())
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        curve.append((d, equity))

    years = (dates[-1] - dates[0]).days / 365.25 or 1 / 365.25
    daily = [b / a - 1 for (_, a), (_, b) in zip(curve, curve[1:])]
    mean = sum(daily) / len(daily) if daily else 0.0
    sd = math.sqrt(sum((r - mean) ** 2 for r in daily) / (len(daily) - 1)) if len(daily) > 1 else 0.0
    by_year: dict[int, list[float]] = {}
    for d, e in curve:
        by_year.setdefault(d.year, []).append(e)
    yearly, prev = {}, start_equity
    for y in sorted(by_year):
        yearly[y] = round(100 * (by_year[y][-1] / prev - 1), 1)
        prev = by_year[y][-1]
    return {
        "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
        "final_equity": round(equity, 2),
        "cagr_pct": round(100 * ((equity / start_equity) ** (1 / years) - 1), 2),
        "ann_vol_pct": round(100 * sd * math.sqrt(TRADING_DAYS), 2),
        "sharpe": round(mean / sd * math.sqrt(TRADING_DAYS), 2) if sd else None,
        "max_drawdown_pct": round(100 * max_dd, 2),
        "trades": trades,
        "trades_per_year": round(trades / years, 1),
        "costs_paid": round(cost_total, 2),
        "avg_gross_exposure": round(gross_sum / len(dates), 2),
        "yearly_return_pct": yearly,
        "curve": curve,
    }
