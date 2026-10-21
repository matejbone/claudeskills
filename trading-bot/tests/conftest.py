from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.broker.base import Broker, Fill  # noqa: E402
from bot.models import Bar  # noqa: E402

CONFIG = """
mode: paper
ib: {{host: 127.0.0.1, port: 7497, client_id: 1}}
strategy: {{name: ema_cross, params: {{fast: 3, slow: 6, atr_period: 3}}}}
markets:
  stocks:
    symbols: [SPY]
    session: {{tz: America/New_York, start: "09:45", last_entry: "15:30", flatten: "15:50"}}
  crypto:
    symbols: [BTC]
    exchange: PAXOS
    qty_decimals: 4
risk: {{risk_per_trade_pct: 1, max_daily_loss_pct: 2, max_open_positions: 2, max_trades_per_day: 5}}
{extra}
"""


@pytest.fixture
def write_config(tmp_path):
    def _write(extra: str = "", text: str | None = None) -> Path:
        p = tmp_path / "config.yaml"
        p.write_text(text if text is not None else CONFIG.format(extra=extra))
        return p
    return _write


def make_bars(closes, start=datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc), minutes=5):
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        out.append(Bar(start + timedelta(minutes=minutes * i), prev, max(prev, c) + 0.2,
                       min(prev, c) - 0.2, c, 1000))
        prev = c
    return out


def wave(n=300, base=100.0, amp=5.0, period=60):
    return [base + amp * math.sin(2 * math.pi * i / period) for i in range(n)]


class FakeBroker(Broker):
    def __init__(self, bars_by_symbol, equity=10_000.0, account="DU123", now=None):
        self.series = bars_by_symbol
        self.idx = {s: len(b) for s, b in bars_by_symbol.items()}
        self._equity = equity
        self.account = account
        self._now = now or datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)  # 11:00 ET
        self.positions: dict[str, float] = {}
        self.orders: list[tuple] = []

    def connect(self): pass
    def disconnect(self): pass
    def account_id(self): return self.account
    def equity(self): return self._equity
    def now(self): return self._now

    def bars(self, inst, count):
        return self.series[inst.symbol][: self.idx[inst.symbol]][-count:]

    def position(self, inst):
        return self.positions.get(inst.symbol, 0.0)

    def open_long(self, inst, qty, ref_price, stop, target):
        self.orders.append(("BUY", inst.symbol, qty, ref_price, stop, target))
        self.positions[inst.symbol] = qty
        return Fill(qty, ref_price)

    def close(self, inst, ref_price):
        qty = self.positions.pop(inst.symbol, 0.0)
        self.orders.append(("SELL", inst.symbol, qty, ref_price))
        return Fill(qty, ref_price)
