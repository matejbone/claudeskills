"""Daily trend-following rebalancer.

Once per weekday, at `rebalance_time` inside working hours, it recomputes
target positions from daily closes and trades only the assets whose position
is off target by more than `rebalance_threshold`. Positions are held overnight
and for days or weeks - that is the strategy. Protection comes from volatility
-scaled sizing, per-asset and gross exposure caps, and a max-drawdown halt
that flattens everything and refuses to restart until a human resets it.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime

from bot.broker.base import Fill
from bot.journal import Journal
from bot.models import Bar, Instrument
from bot.trend.config import TrendConfig
from bot.trend.signal import realized_vol, target_weights, trend_signal

log = logging.getLogger("bot")


class TrendBroker(ABC):
    @abstractmethod
    def account_id(self) -> str: ...
    @abstractmethod
    def now(self) -> datetime: ...
    @abstractmethod
    def equity(self) -> float: ...
    @abstractmethod
    def daily_bars(self, inst: Instrument, count: int) -> list[Bar]:
        """Most recent `count` completed daily bars, oldest first."""
    @abstractmethod
    def position(self, inst: Instrument) -> float: ...
    @abstractmethod
    def fx_rate(self, frm: str, to: str) -> float:
        """Units of `to` per one unit of `frm`."""
    @abstractmethod
    def order(self, inst: Instrument, qty: float, ref_price: float) -> Fill:
        """Buy (qty > 0) or sell (qty < 0). Returns the signed filled quantity."""


@dataclass
class TrendState:
    last_rebalance: str = ""
    peak_equity: float = 0.0
    halted: bool = False
    halt_reason: str = ""


class TrendEngine:
    def __init__(self, cfg: TrendConfig, broker: TrendBroker, journal: Journal):
        self.cfg, self.broker, self.journal = cfg, broker, journal
        self.state = self._load()
        self.stopped = False

    # --- state ---------------------------------------------------------------
    def _load(self) -> TrendState:
        if self.cfg.state_file.exists():
            return TrendState(**json.loads(self.cfg.state_file.read_text()))
        return TrendState()

    def _save(self) -> None:
        self.cfg.state_file.write_text(json.dumps(asdict(self.state), indent=2))

    # --- startup -------------------------------------------------------------
    def preflight(self) -> None:
        acct = self.broker.account_id()
        is_paper = acct.startswith("DU")
        if not self.cfg.live and not is_paper:
            raise RuntimeError(f"paper mode but connected to non-paper account {acct}; refusing")
        if self.cfg.live and is_paper:
            raise RuntimeError(f"live mode but connected to paper account {acct}")
        if self.state.halted:
            raise RuntimeError(f"bot is halted ({self.state.halt_reason}). Review the journal, then "
                               f"delete {self.cfg.state_file.name} to reset.")
        self.journal.write(self.broker.now(), "START", note=f"trend mode={self.cfg.mode} account={acct}")

    # --- helpers -------------------------------------------------------------
    def _local(self, now: datetime) -> datetime:
        oh = self.cfg.operating_hours
        return now.astimezone(oh.tz) if oh else now

    def _flatten_all(self, reason: str) -> None:
        for a in self.cfg.assets:
            pos = self.broker.position(a.inst)
            if pos:
                bars = self.broker.daily_bars(a.inst, 1)
                fill = self.broker.order(a.inst, -pos, bars[-1].close if bars else 0.0)
                self.journal.write(self.broker.now(), "FLATTEN", a.inst.symbol, qty=fill.qty,
                                   price=fill.price, note=reason)

    # --- main step -----------------------------------------------------------
    def step(self) -> None:
        if self.stopped:
            return
        now = self.broker.now()
        if self.cfg.kill_switch_file.exists():
            self._flatten_all("kill switch")
            self.journal.write(now, "STOP", note="kill switch file found")
            self.stopped = True
            return

        oh = self.cfg.operating_hours
        local = self._local(now)
        if oh and (local.weekday() not in oh.days or local.time() >= oh.stop):
            # Positions are meant to be held overnight; just stop the program.
            self.journal.write(now, "STOP", note="end of working hours (positions held)")
            self.stopped = True
            return

        equity = self.broker.equity()
        self.state.peak_equity = max(self.state.peak_equity, equity)
        dd = (self.state.peak_equity - equity) / self.state.peak_equity * 100
        if dd >= self.cfg.max_drawdown_pct:
            self.state.halted = True
            self.state.halt_reason = f"drawdown {dd:.1f}% >= {self.cfg.max_drawdown_pct}%"
            self._save()
            self.journal.write(now, "HALT", note=self.state.halt_reason)
            self._flatten_all("max drawdown")
            self.stopped = True
            return
        self._save()

        today = local.date().isoformat()
        if self.state.last_rebalance == today or local.time() < self.cfg.rebalance_time:
            return
        if oh and local.time() >= oh.last_entry:
            return
        self.rebalance(equity)
        self.state.last_rebalance = today
        self._save()

    def rebalance(self, equity: float) -> None:
        now = self.broker.now()
        need = max(self.cfg.lookbacks) + 5
        closes: dict[str, list[float]] = {}
        for a in self.cfg.assets:
            try:
                bars = self.broker.daily_bars(a.inst, need)
            except Exception as exc:  # no data -> leave this asset untouched today
                log.exception("bars for %s", a.inst.symbol)
                self.journal.write(now, "ERROR", a.inst.symbol, note=f"no data, skipped: {exc!r}")
                continue
            closes[a.inst.symbol] = [b.close for b in bars]

        signals, vols = {}, {}
        for sym, c in closes.items():
            sig = trend_signal(c, self.cfg.lookbacks)
            signals[sym] = sig if sig is not None else 0.0
            vols[sym] = realized_vol(c, self.cfg.vol_window) or 0.0
        weights = target_weights(signals, vols, target_vol_pct=self.cfg.target_vol_pct,
                                 max_weight=self.cfg.max_weight, max_gross=self.cfg.max_gross,
                                 long_only=self.cfg.long_only)

        for a in self.cfg.assets:
            sym = a.inst.symbol
            if sym not in weights or not closes[sym]:
                continue
            try:
                self._trade_to_target(a, weights[sym], closes[sym][-1], equity,
                                      signals[sym], vols[sym])
            except Exception as exc:
                log.exception("rebalance %s", sym)
                self.journal.write(now, "ERROR", sym, note=repr(exc))

    def _trade_to_target(self, a, weight, price, equity, signal, vol) -> None:
        inst = a.inst
        rate = self.broker.fx_rate(self.cfg.account_currency, inst.currency)
        target = round(weight * equity * rate / price, inst.qty_decimals)
        current = self.broker.position(inst)
        delta = round(target - current, inst.qty_decimals)
        note = f"w={weight:+.3f} signal={signal:+.2f} vol={vol:.1%}"
        if delta == 0:
            return
        closing = target == 0 or (current != 0 and (target > 0) != (current > 0))
        big_enough = abs(delta) >= self.cfg.rebalance_threshold * max(abs(target), abs(current))
        notional = abs(delta) * price / rate
        if not closing and (not big_enough or notional < a.min_order):
            self.journal.write(self.broker.now(), "HOLD", inst.symbol, qty=current, price=price,
                               note=f"{note} target={target} (change too small)")
            return
        fill = self.broker.order(inst, delta, price)
        self.journal.write(self.broker.now(), "REBALANCE", inst.symbol, qty=fill.qty,
                           price=fill.price or price, note=f"{note} {current} -> {target}")
