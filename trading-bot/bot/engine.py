from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from bot.broker.base import Broker
from bot.config import Config
from bot.journal import Journal
from bot.models import Action, Instrument, Market, OpenTrade
from bot.risk import RiskManager
from bot.strategies.base import Strategy

log = logging.getLogger("bot")


class Engine:
    """Runs one strategy across all configured instruments.

    Each `step()` is one poll: check the kill switch and daily loss limit,
    manage open trades (stop / target / strategy exit / end-of-day flatten),
    then look for new entries on freshly closed bars.
    """

    def __init__(self, cfg: Config, broker: Broker, strategy: Strategy,
                 risk: RiskManager, journal: Journal):
        self.cfg, self.broker, self.strategy, self.risk, self.journal = cfg, broker, strategy, risk, journal
        self.trades_file: Path = cfg.state_file.with_name(cfg.state_file.stem + "_trades.json")
        self.trades: dict[str, OpenTrade] = self._load_trades()
        self.last_bar: dict[str, datetime] = {}
        self.stopped = False

    # --- startup checks ------------------------------------------------------
    def preflight(self) -> None:
        acct = self.broker.account_id()
        is_paper_acct = acct.startswith("DU")  # IB paper accounts start with DU
        if not self.cfg.live and not is_paper_acct:
            raise RuntimeError(f"paper mode but connected to non-paper account {acct}; refusing")
        if self.cfg.live and is_paper_acct:
            raise RuntimeError(f"live mode but connected to paper account {acct}")
        now = self.broker.now()
        self.journal.write(now, "START", note=f"mode={self.cfg.mode} account={acct} "
                                              f"strategy={self.strategy.name}")
        for inst in self.cfg.instruments:
            pos = self.broker.position(inst)
            if pos and inst.key not in self.trades:
                self.journal.write(now, "UNMANAGED", inst.symbol, qty=pos,
                                   note="existing position not opened by bot; left untouched")

    # --- persistence ---------------------------------------------------------
    def _load_trades(self) -> dict[str, OpenTrade]:
        if not self.trades_file.exists():
            return {}
        by_key = {i.key: i for i in self.cfg.instruments}
        out = {}
        for key, d in json.loads(self.trades_file.read_text()).items():
            if key in by_key:
                out[key] = OpenTrade(by_key[key], d["qty"], d["entry"], d["stop"], d["target"],
                                     datetime.fromisoformat(d["opened_at"]), d.get("meta", {}))
        return out

    def _save_trades(self) -> None:
        self.trades_file.write_text(json.dumps({
            k: {"qty": t.qty, "entry": t.entry, "stop": t.stop, "target": t.target,
                "opened_at": t.opened_at.isoformat(), "meta": t.meta}
            for k, t in self.trades.items()}, indent=2))

    # --- helpers -------------------------------------------------------------
    def _local(self, now: datetime) -> datetime:
        tz = self.cfg.stock_session.tz if self.cfg.stock_session else timezone.utc
        return now.astimezone(tz)

    def _stock_window(self, now: datetime) -> tuple[bool, bool]:
        """(entries_allowed, must_flatten) for stocks."""
        s = self.cfg.stock_session
        if s is None:
            return True, False
        local = now.astimezone(s.tz)
        if local.weekday() >= 5:
            return False, False
        t = local.time()
        return s.start <= t < s.last_entry, t >= s.flatten

    def _close(self, inst: Instrument, price: float, reason: str) -> None:
        trade = self.trades.get(inst.key)
        fill = self.broker.close(inst, price)
        now = self.broker.now()
        pnl = (fill.price - trade.entry) * fill.qty if trade and fill.qty else None
        self.journal.write(now, "EXIT", inst.symbol, qty=fill.qty, price=fill.price or price,
                           pnl=round(pnl, 2) if pnl is not None else None, note=reason)
        if self.broker.position(inst) <= 0:
            if trade and inst.market is Market.STOCKS and \
                    self._local(trade.opened_at).date() == self._local(now).date():
                self.risk.record_day_trade(self._local(now).date())
            self.trades.pop(inst.key, None)
        elif trade:
            trade.meta["exiting"] = reason  # partial fill: retry next step
        self._save_trades()

    def flatten_all(self, reason: str) -> None:
        for inst in self.cfg.instruments:
            if inst.key in self.trades:
                bars = self.broker.bars(inst, 1)
                self._close(inst, bars[-1].close if bars else self.trades[inst.key].entry, reason)

    # --- main step -----------------------------------------------------------
    def step(self) -> None:
        if self.stopped:
            return
        now = self.broker.now()
        if self.cfg.kill_switch_file.exists():
            self.flatten_all("kill switch")
            self.journal.write(now, "STOP", note="kill switch file found")
            self.stopped = True
            return

        equity = self.broker.equity()
        today = self._local(now).date()
        self.risk.start_day(today, equity)
        was_halted = self.risk.state.halted
        if self.risk.update_equity(equity):
            if not was_halted:
                self.journal.write(now, "HALT", note=self.risk.state.halt_reason)
            self.flatten_all("circuit breaker")
            return

        entries_ok, must_flatten = self._stock_window(now)
        for inst in self.cfg.instruments:
            try:
                self._step_instrument(inst, now, equity, today,
                                      entries_ok or inst.market is Market.CRYPTO,
                                      must_flatten and inst.market is Market.STOCKS)
            except Exception as exc:  # one bad symbol shouldn't stop the others
                log.exception("error on %s", inst.symbol)
                self.journal.write(now, "ERROR", inst.symbol, note=repr(exc))

    def _step_instrument(self, inst, now, equity, today, entries_ok, must_flatten) -> None:
        bars = self.broker.bars(inst, self.strategy.warmup + 5)
        if not bars:
            return
        last = bars[-1]
        pos = self.broker.position(inst)
        trade = self.trades.get(inst.key)

        if trade:
            if pos <= 0:  # closed broker-side (stop/target bracket leg)
                self.journal.write(now, "CLOSED_AT_BROKER", inst.symbol, note="bracket leg filled")
                if inst.market is Market.STOCKS and self._local(trade.opened_at).date() == today:
                    self.risk.record_day_trade(today)
                self.trades.pop(inst.key)
                self._save_trades()
                return
            if "exiting" in trade.meta:
                return self._close(inst, last.close, trade.meta["exiting"])
            if must_flatten:
                return self._close(inst, last.close, "end of day flatten")
            if last.low <= trade.stop:
                return self._close(inst, last.close, "stop")
            if trade.target is not None and last.high >= trade.target:
                return self._close(inst, last.close, "target")

        if self.last_bar.get(inst.key) == last.ts:
            return  # already evaluated this bar
        self.last_bar[inst.key] = last.ts

        sig = self.strategy.signal(bars, in_position=trade is not None)
        if sig is None:
            return
        if sig.action is Action.EXIT and trade:
            return self._close(inst, last.close, sig.reason or "strategy exit")
        if sig.action is not Action.BUY or trade or pos != 0 or not entries_ok or must_flatten:
            return

        ok, why = self.risk.can_open(inst, len(self.trades), equity, today)
        if not ok:
            self.journal.write(now, "SKIP", inst.symbol, note=why)
            return
        qty = self.risk.size(inst, equity, last.close, sig.stop)
        if qty <= 0:
            self.journal.write(now, "SKIP", inst.symbol, note="size rounds to zero")
            return
        fill = self.broker.open_long(inst, qty, last.close, sig.stop, sig.target)
        if fill.qty <= 0:
            self.journal.write(now, "NO_FILL", inst.symbol, qty=qty, price=last.close)
            return
        self.risk.record_entry()
        self.trades[inst.key] = OpenTrade(inst, fill.qty, fill.price, sig.stop, sig.target, now)
        self._save_trades()
        self.journal.write(now, "ENTRY", inst.symbol, qty=fill.qty, price=fill.price,
                           stop=round(sig.stop, 4), target=round(sig.target, 4) if sig.target else None,
                           note=sig.reason)
