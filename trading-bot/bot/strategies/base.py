from __future__ import annotations

from abc import ABC, abstractmethod

from bot.models import Bar, Signal


class Strategy(ABC):
    """A strategy turns recent bars into a Signal.

    It never sizes positions or places orders - the risk manager and engine do
    that - so the same strategy runs unchanged in backtests, paper and live.
    """

    name: str = "base"

    def __init__(self, **params):
        self.params = params

    @property
    @abstractmethod
    def warmup(self) -> int:
        """Number of bars needed before the strategy can produce signals."""

    @abstractmethod
    def signal(self, bars: list[Bar], in_position: bool) -> Signal | None:
        """Return BUY (with stop, optional target) when flat, EXIT when in a
        position, or None to do nothing. `bars[-1]` is the last closed bar."""
