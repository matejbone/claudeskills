from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from bot.models import Bar, Instrument


@dataclass(frozen=True)
class Fill:
    qty: float
    price: float


class Broker(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def account_id(self) -> str: ...

    @abstractmethod
    def equity(self) -> float:
        """Net liquidation value in account currency."""

    @abstractmethod
    def bars(self, inst: Instrument, count: int) -> list[Bar]:
        """The most recent `count` *closed* bars, oldest first."""

    @abstractmethod
    def position(self, inst: Instrument) -> float: ...

    @abstractmethod
    def open_long(self, inst: Instrument, qty: float, ref_price: float,
                  stop: float, target: float | None) -> Fill:
        """Buy up to `qty` with a marketable limit. Returns what actually filled
        (qty 0 if nothing). Where the venue supports it, also places a
        broker-side protective stop/target."""

    @abstractmethod
    def close(self, inst: Instrument, ref_price: float) -> Fill:
        """Cancel working orders for `inst` and sell the whole position."""

    @abstractmethod
    def now(self) -> datetime: ...
