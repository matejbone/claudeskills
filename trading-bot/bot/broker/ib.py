"""Interactive Brokers adapter (via ib_async). Requires TWS or IB Gateway
running locally with the API enabled.

Stocks: bracket order (IOC limit entry + broker-side stop-loss and take-profit),
so the stop still works if the bot crashes.
Crypto (PAXOS): IB doesn't support bracket/stop orders here, so entries/exits
are IOC limit orders and the bot itself enforces the stop each poll.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.broker.base import Broker, Fill
from bot.models import Bar, Instrument, Market

_UNIT_SECONDS = {"sec": 1, "secs": 1, "min": 60, "mins": 60, "hour": 3600, "hours": 3600,
                 "day": 86400, "days": 86400}
FILL_WAIT_SECONDS = 5


def bar_seconds(bar_size: str) -> int:
    n, unit = bar_size.split()
    return int(n) * _UNIT_SECONDS[unit]


class IBBroker(Broker):
    def __init__(self, host: str, port: int, client_id: int, bar_size: str, slippage_pct: float):
        from ib_async import IB  # imported lazily so tests/backtests don't need it

        self.ib = IB()
        self.host, self.port, self.client_id = host, port, client_id
        self.bar_size = bar_size
        self.bar_secs = bar_seconds(bar_size)
        self.slip = slippage_pct / 100
        self._contracts: dict[str, object] = {}

    # --- connection ----------------------------------------------------------
    def connect(self) -> None:
        self.ib.connect(self.host, self.port, clientId=self.client_id)

    def disconnect(self) -> None:
        self.ib.disconnect()

    def account_id(self) -> str:
        accounts = self.ib.managedAccounts()
        if len(accounts) != 1:
            raise RuntimeError(f"expected exactly one account, got {accounts}")
        return accounts[0]

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    # --- data ----------------------------------------------------------------
    def contract(self, inst: Instrument):
        if inst.key not in self._contracts:
            from ib_async import Crypto, Stock

            c = (Stock(inst.symbol, inst.exchange, inst.currency) if inst.market is Market.STOCKS
                 else Crypto(inst.symbol, inst.exchange, inst.currency))
            self.ib.qualifyContracts(c)
            self._contracts[inst.key] = c
        return self._contracts[inst.key]

    def equity(self) -> float:
        for v in self.ib.accountSummary(self.account_id()):
            if v.tag == "NetLiquidation":
                return float(v.value)
        raise RuntimeError("NetLiquidation not available")

    def bars(self, inst: Instrument, count: int) -> list[Bar]:
        stocks = inst.market is Market.STOCKS
        raw = self.ib.reqHistoricalData(
            self.contract(inst), endDateTime="", durationStr="5 D" if stocks else "2 D",
            barSizeSetting=self.bar_size, whatToShow="TRADES" if stocks else "AGGTRADES",
            useRTH=stocks, formatDate=2,
        )
        now = self.now()
        out = []
        for b in raw:
            ts = b.date if isinstance(b.date, datetime) else datetime.combine(b.date, datetime.min.time())
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts + timedelta(seconds=self.bar_secs) > now:
                continue  # still forming
            out.append(Bar(ts, b.open, b.high, b.low, b.close, float(b.volume)))
        return out[-count:]

    def position(self, inst: Instrument) -> float:
        con_id = self.contract(inst).conId
        return sum(float(p.position) for p in self.ib.positions() if p.contract.conId == con_id)

    # --- orders --------------------------------------------------------------
    def _wait(self, trades) -> None:
        for _ in range(FILL_WAIT_SECONDS * 10):
            if all(t.isDone() for t in trades):
                return
            self.ib.sleep(0.1)

    def open_long(self, inst, qty, ref_price, stop, target) -> Fill:
        from ib_async import LimitOrder

        c = self.contract(inst)
        limit = round(ref_price * (1 + self.slip), 2)
        if inst.market is Market.STOCKS:
            bracket = self.ib.bracketOrder("BUY", qty, limit,
                                           round(target or ref_price * 10, 2), round(stop, 2))
            bracket.parent.tif = "IOC"
            for o in (bracket.takeProfit, bracket.stopLoss):
                o.tif = "DAY"
            # The stop leg is the one with transmit=True, so it goes last.
            orders = [bracket.parent, bracket.takeProfit, bracket.stopLoss] if target else \
                     [bracket.parent, bracket.stopLoss]
            placed = [self.ib.placeOrder(c, o) for o in orders]
            entry = placed[0]
            self._wait([entry])
        else:
            entry = self.ib.placeOrder(c, LimitOrder("BUY", qty, limit, tif="IOC"))
            self._wait([entry])
        filled = float(entry.orderStatus.filled)
        return Fill(filled, float(entry.orderStatus.avgFillPrice) if filled else 0.0)

    def close(self, inst, ref_price) -> Fill:
        from ib_async import LimitOrder, MarketOrder

        c = self.contract(inst)
        for t in self.ib.openTrades():
            if t.contract.conId == c.conId:
                self.ib.cancelOrder(t.order)
        self.ib.sleep(1)
        qty = self.position(inst)
        if qty <= 0:
            return Fill(0.0, 0.0)
        order = (MarketOrder("SELL", qty) if inst.market is Market.STOCKS
                 else LimitOrder("SELL", qty, round(ref_price * (1 - self.slip), 2), tif="IOC"))
        trade = self.ib.placeOrder(c, order)
        self._wait([trade])
        filled = float(trade.orderStatus.filled)
        return Fill(filled, float(trade.orderStatus.avgFillPrice) if filled else 0.0)
