from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from bot.config import RiskConfig
from bot.models import Instrument, Market

PDT_EQUITY = 25_000
PDT_MAX_DAY_TRADES = 3


@dataclass
class RiskState:
    day: str = ""
    day_start_equity: float = 0.0
    trades_today: int = 0
    halted: bool = False
    halt_reason: str = ""
    day_trade_dates: list[str] = field(default_factory=list)


class RiskManager:
    """Position sizing plus hard limits. State is persisted so a restart
    doesn't reset the daily loss limit or trade counters."""

    def __init__(self, cfg: RiskConfig, state_file: Path | None = None, pdt_guard: bool = True):
        self.cfg = cfg
        self.state_file = state_file
        self.pdt_guard = pdt_guard
        self.state = self._load()

    # --- persistence -------------------------------------------------------
    def _load(self) -> RiskState:
        if self.state_file and self.state_file.exists():
            return RiskState(**json.loads(self.state_file.read_text()))
        return RiskState()

    def save(self) -> None:
        if self.state_file:
            self.state_file.write_text(json.dumps(asdict(self.state), indent=2))

    # --- day handling ------------------------------------------------------
    def start_day(self, today: date, equity: float) -> None:
        if self.state.day != today.isoformat():
            self.state.day = today.isoformat()
            self.state.day_start_equity = equity
            self.state.trades_today = 0
            self.state.halted = False
            self.state.halt_reason = ""
            self.save()

    def update_equity(self, equity: float) -> bool:
        """Trip the circuit breaker if today's loss exceeds the limit.
        Returns True when trading is (now) halted."""
        start = self.state.day_start_equity
        if start > 0 and not self.state.halted:
            loss_pct = (start - equity) / start * 100
            if loss_pct >= self.cfg.max_daily_loss_pct:
                self.halt(f"daily loss {loss_pct:.2f}% >= {self.cfg.max_daily_loss_pct}%")
        return self.state.halted

    def halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = reason
        self.save()

    # --- sizing ------------------------------------------------------------
    def size(self, inst: Instrument, equity: float, entry: float, stop: float) -> float:
        """Quantity so that hitting the stop loses risk_per_trade_pct of equity,
        capped at max_position_pct of equity. Returns 0 if not tradable,
        including stops so tight that fees and slippage would dominate."""
        per_unit = entry - stop
        if equity <= 0 or entry <= 0 or per_unit <= 0:
            return 0.0
        if per_unit / entry * 100 < self.cfg.min_stop_pct:
            return 0.0
        qty = min(equity * self.cfg.risk_per_trade_pct / 100 / per_unit,
                  equity * self.cfg.max_position_pct / 100 / entry)
        step = 10 ** -inst.qty_decimals
        return round(math.floor(qty / step) * step, inst.qty_decimals)

    # --- gates -------------------------------------------------------------
    def can_open(self, inst: Instrument, open_positions: int, equity: float, today: date) -> tuple[bool, str]:
        if self.state.halted:
            return False, f"halted: {self.state.halt_reason}"
        if open_positions >= self.cfg.max_open_positions:
            return False, "max open positions"
        if self.state.trades_today >= self.cfg.max_trades_per_day:
            return False, "max trades per day"
        if (inst.market is Market.STOCKS and self.pdt_guard and equity < PDT_EQUITY
                and self.day_trades_last_5(today) >= PDT_MAX_DAY_TRADES):
            return False, "PDT guard: 3 day trades in last 5 business days"
        return True, ""

    def record_entry(self) -> None:
        self.state.trades_today += 1
        self.save()

    def record_day_trade(self, today: date) -> None:
        self.state.day_trade_dates.append(today.isoformat())
        cutoff = (today - timedelta(days=14)).isoformat()
        self.state.day_trade_dates = [d for d in self.state.day_trade_dates if d >= cutoff]
        self.save()

    def day_trades_last_5(self, today: date) -> int:
        days, d = set(), today
        while len(days) < 5:
            if d.weekday() < 5:
                days.add(d.isoformat())
            d -= timedelta(days=1)
        return sum(1 for x in self.state.day_trade_dates if x in days)
