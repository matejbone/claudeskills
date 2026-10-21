"""Time-series momentum ("trend following") on daily closes.

Signal = average of sign(past return) over several lookbacks, in [-1, 1]:
+1 when every horizon is up, -1 when every horizon is down, in between when
they disagree. Positions are scaled so each asset contributes similar risk.
Based on Moskowitz, Ooi & Pedersen (2012), "Time series momentum", JFE.
"""
from __future__ import annotations

import math

TRADING_DAYS = 252


def trend_signal(closes: list[float], lookbacks: list[int]) -> float | None:
    """None if there isn't enough history for the longest lookback."""
    if len(closes) <= max(lookbacks):
        return None
    votes = []
    for n in lookbacks:
        r = closes[-1] / closes[-1 - n] - 1
        votes.append(1.0 if r > 0 else -1.0 if r < 0 else 0.0)
    return sum(votes) / len(votes)


def realized_vol(closes: list[float], window: int) -> float | None:
    """Annualized standard deviation of daily log returns over `window` days."""
    if len(closes) <= window:
        return None
    rets = [math.log(b / a) for a, b in zip(closes[-window - 1:-1], closes[-window:])]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def target_weights(signals: dict[str, float], vols: dict[str, float], *, target_vol_pct: float,
                   max_weight: float, max_gross: float, long_only: set[str]) -> dict[str, float]:
    """Weight = signal x (per-asset vol budget / asset vol), capped per asset,
    then scaled down together if gross exposure exceeds max_gross.

    Weight 1.0 means a position worth 100% of equity (negative = short)."""
    active = [k for k in signals if vols.get(k)]
    if not active:
        return {k: 0.0 for k in signals}
    per_asset_vol = target_vol_pct / 100 / math.sqrt(len(active))
    w = {}
    for k in signals:
        s = signals[k]
        if k in long_only:
            s = max(s, 0.0)
        if not vols.get(k) or s == 0:
            w[k] = 0.0
            continue
        raw = s * per_asset_vol / vols[k]
        w[k] = max(-max_weight, min(max_weight, raw))
    gross = sum(abs(v) for v in w.values())
    if gross > max_gross:
        w = {k: v * max_gross / gross for k, v in w.items()}
    return w
