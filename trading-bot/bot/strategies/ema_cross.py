from __future__ import annotations

from bot.models import Action, Bar, Signal
from bot.strategies.base import Strategy
from bot.strategies.indicators import atr, ema


class EmaCross(Strategy):
    """Sample strategy: long when the fast EMA crosses above the slow EMA,
    exit when it crosses back below. Stop = ATR multiple below entry,
    target = stop distance x reward_risk.

    This is a placeholder to exercise the framework, not a proven edge.
    """

    name = "ema_cross"

    def __init__(self, fast=9, slow=21, atr_period=14, atr_stop_mult=1.5, reward_risk=2.0):
        if fast >= slow:
            raise ValueError("fast must be shorter than slow")
        super().__init__(fast=fast, slow=slow, atr_period=atr_period,
                         atr_stop_mult=atr_stop_mult, reward_risk=reward_risk)
        self.fast, self.slow = fast, slow
        self.atr_period, self.atr_stop_mult, self.reward_risk = atr_period, atr_stop_mult, reward_risk

    @property
    def warmup(self) -> int:
        return max(self.slow * 3, self.atr_period + 1)

    def signal(self, bars: list[Bar], in_position: bool) -> Signal | None:
        if len(bars) < self.warmup:
            return None
        closes = [b.close for b in bars]
        f, s = ema(closes, self.fast), ema(closes, self.slow)
        crossed_up = f[-2] <= s[-2] and f[-1] > s[-1]
        crossed_down = f[-2] >= s[-2] and f[-1] < s[-1]

        if in_position:
            return Signal(Action.EXIT, reason="ema cross down") if crossed_down else None
        if not crossed_up:
            return None
        price = closes[-1]
        stop_dist = atr(bars, self.atr_period) * self.atr_stop_mult
        if stop_dist <= 0:
            return None
        return Signal(Action.BUY, stop=price - stop_dist,
                      target=price + stop_dist * self.reward_risk, reason="ema cross up")
