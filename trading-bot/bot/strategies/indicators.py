from __future__ import annotations

from bot.models import Bar


def ema(values: list[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    k = 2.0 / (period + 1)
    out: list[float] = []
    for i, v in enumerate(values):
        out.append(v if i == 0 else v * k + out[-1] * (1 - k))
    return out


def atr(bars: list[Bar], period: int) -> float:
    """Simple-average true range over the last `period` bars."""
    if len(bars) < period + 1:
        raise ValueError("not enough bars for ATR")
    trs = []
    for prev, cur in zip(bars[-period - 1 : -1], bars[-period:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs) / period
