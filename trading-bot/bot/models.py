from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Market(str, Enum):
    STOCKS = "stocks"
    CRYPTO = "crypto"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: Market
    exchange: str
    currency: str = "USD"
    qty_decimals: int = 0

    @property
    def key(self) -> str:
        return f"{self.market.value}:{self.symbol}"


@dataclass(frozen=True)
class Bar:
    ts: datetime  # bar start, timezone-aware
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class Action(str, Enum):
    BUY = "BUY"    # open a long position
    EXIT = "EXIT"  # close the current position


@dataclass(frozen=True)
class Signal:
    action: Action
    stop: float | None = None
    target: float | None = None
    reason: str = ""


@dataclass
class OpenTrade:
    """Bot-side record of a position it opened, used for stop/target checks."""

    instrument: Instrument
    qty: float
    entry: float
    stop: float
    target: float | None
    opened_at: datetime
    meta: dict = field(default_factory=dict)
