from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest
from conftest import FakeBroker  # noqa: F401  (keeps sys.path setup)

from bot.broker.base import Fill
from bot.journal import Journal
from bot.models import Bar
from bot.trend.backtest import run_trend_backtest
from bot.trend.config import load_trend_config
from bot.trend.engine import TrendBroker, TrendEngine
from bot.trend.signal import realized_vol, target_weights, trend_signal

TREND_CFG = """
mode: paper
ib: {{port: 7497}}
account_currency: EUR
operating_hours: {{tz: Europe/Berlin, start: "08:00", last_entry: "15:30", stop: "15:55"}}
rebalance_time: "09:30"
strategy: {{lookbacks: [5, 10, 20], vol_window: 10}}
risk: {{target_vol_pct: 10, max_weight_per_asset: 0.8, max_gross_exposure: 1.5,
        rebalance_threshold: 0.25, max_drawdown_pct: 20}}
assets:
  - {{symbol: EURUSD, market: forex, currency: USD, min_order: 100}}
  - {{symbol: SXR8, market: stocks, currency: EUR, min_order: 100}}
{extra}
"""


def daily(closes, start=date(2024, 1, 1)):
    out, d = [], start
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(Bar(datetime(d.year, d.month, d.day, tzinfo=timezone.utc), c, c * 1.002, c * 0.998, c))
        d += timedelta(days=1)
    return out


def trending(n, start, drift, noise=0.004, phase=0.0):
    return [start * math.exp(drift * i + noise * math.sin(i * 1.7 + phase)) for i in range(n)]


@pytest.fixture
def tcfg(tmp_path):
    def _write(extra=""):
        p = tmp_path / "trend.yaml"
        p.write_text(TREND_CFG.format(extra=extra))
        return load_trend_config(p, env={})
    return _write


class FakeTrendBroker(TrendBroker):
    def __init__(self, series, equity=10_000.0, account="DU1", now=None, rates=None):
        self.series, self._equity, self.account = series, equity, account
        self._now = now or datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)  # Mon 10:00 CEST
        self.positions: dict[str, float] = {}
        self.orders: list[tuple[str, float]] = []
        self.rates = rates or {}

    def account_id(self): return self.account
    def now(self): return self._now
    def equity(self): return self._equity
    def daily_bars(self, inst, count): return self.series[inst.symbol][-count:]
    def position(self, inst): return self.positions.get(inst.symbol, 0.0)
    def fx_rate(self, frm, to): return 1.0 if frm == to else self.rates.get((frm, to), 1.1)

    def order(self, inst, qty, ref_price):
        self.orders.append((inst.symbol, qty))
        self.positions[inst.symbol] = round(self.positions.get(inst.symbol, 0.0) + qty, 8)
        return Fill(qty, ref_price)


# --- signal math ---------------------------------------------------------------
def test_trend_signal_votes():
    up = list(range(1, 40))
    assert trend_signal(up, [5, 10, 20]) == 1.0
    assert trend_signal(up[::-1], [5, 10, 20]) == -1.0
    mixed = [10] * 15 + [12] * 15 + [11] * 5  # up over 20 days, down over 5 and 10
    assert -1 < trend_signal(mixed, [5, 10, 20]) < 1
    assert trend_signal([1, 2, 3], [5]) is None


def test_realized_vol_annualized():
    closes = [100 * (1.01 if i % 2 else 0.99) ** 1 for i in range(100)]
    v = realized_vol(closes, 60)
    assert 0.2 < v < 0.5  # ~2% daily swings -> ~32% annualized


def test_target_weights_caps_and_long_only():
    w = target_weights({"A": 1.0, "B": -1.0, "C": -1.0}, {"A": 0.05, "B": 0.05, "C": 0.2},
                       target_vol_pct=10, max_weight=0.5, max_gross=0.9, long_only={"C"})
    assert w["C"] == 0.0                       # long-only asset with short signal -> flat
    assert w["A"] > 0 > w["B"]
    assert abs(w["A"]) <= 0.5 and abs(w["B"]) <= 0.5
    assert sum(abs(v) for v in w.values()) <= 0.9 + 1e-9


# --- config ----------------------------------------------------------------
def test_trend_config_defaults(tcfg):
    cfg = tcfg()
    assert cfg.long_only == {"SXR8"}  # forex can short, ETFs long-only by default
    assert cfg.assets[0].inst.exchange == "IDEALPRO"


def test_trend_config_rejects_crypto_and_bad_limits(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text(TREND_CFG.format(extra="  - {symbol: BTC, market: crypto}"))
    with pytest.raises(ValueError, match="crypto"):
        load_trend_config(p, env={})
    p.write_text(TREND_CFG.format(extra="").replace("max_gross_exposure: 1.5", "max_gross_exposure: 5"))
    with pytest.raises(ValueError, match="max_gross"):
        load_trend_config(p, env={})


def test_example_config_loads():
    from pathlib import Path
    cfg = load_trend_config(Path(__file__).parents[1] / "trend.example.yaml", env={})
    assert len(cfg.assets) == 10 and cfg.mode == "paper"


# --- engine ----------------------------------------------------------------
def _series():
    return {"EURUSD": daily(trending(80, 1.08, -0.002)),   # downtrend -> short
            "SXR8": daily(trending(80, 500, 0.002))}       # uptrend -> long


def test_engine_rebalances_once_per_day(tcfg):
    cfg = tcfg()
    b = FakeTrendBroker(_series())
    e = TrendEngine(cfg, b, Journal(cfg.journal))
    e.preflight()
    e.step()
    assert b.positions["EURUSD"] < 0 < b.positions["SXR8"]
    n = len(b.orders)
    b._now += timedelta(hours=1)
    e.step()
    assert len(b.orders) == n  # already rebalanced today


def test_engine_waits_for_rebalance_time(tcfg):
    cfg = tcfg()
    b = FakeTrendBroker(_series(), now=datetime(2026, 10, 19, 6, 30, tzinfo=timezone.utc))  # 08:30
    e = TrendEngine(cfg, b, Journal(cfg.journal))
    e.step()
    assert not b.orders and not e.stopped


def test_engine_respects_threshold(tcfg):
    cfg = tcfg()
    b = FakeTrendBroker(_series())
    e = TrendEngine(cfg, b, Journal(cfg.journal))
    e.step()
    before = dict(b.positions)
    # next day, equity up 5%: targets move ~5% < 25% threshold -> no trades
    b._now += timedelta(days=1)
    b._equity *= 1.05
    e.step()
    assert b.positions == before
    assert "change too small" in cfg.journal.read_text()


def test_engine_closes_when_trend_flips(tcfg):
    cfg = tcfg()
    s = _series()
    b = FakeTrendBroker(s)
    e = TrendEngine(cfg, b, Journal(cfg.journal))
    e.step()
    assert b.positions["SXR8"] > 0
    crash = [s["SXR8"][-1].close * (1 - 0.01 * i) for i in range(1, 25)]
    b.series["SXR8"] = s["SXR8"] + daily(crash, start=s["SXR8"][-1].ts.date() + timedelta(days=1))
    b._now += timedelta(days=1)
    e.step()
    assert b.positions["SXR8"] == 0  # long-only ETF goes flat, not short


def test_engine_end_of_hours_keeps_positions(tcfg):
    cfg = tcfg()
    b = FakeTrendBroker(_series())
    e = TrendEngine(cfg, b, Journal(cfg.journal))
    e.step()
    held = dict(b.positions)
    b._now = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)  # 16:00 CEST
    e.step()
    assert e.stopped and b.positions == held


def test_engine_drawdown_halt_flattens_and_blocks_restart(tcfg):
    cfg = tcfg()
    b = FakeTrendBroker(_series())
    e = TrendEngine(cfg, b, Journal(cfg.journal))
    e.step()
    b._equity = 7_900  # -21% from peak
    e.step()
    assert e.stopped and not any(b.positions.values())
    with pytest.raises(RuntimeError, match="halted"):
        TrendEngine(cfg, b, Journal(cfg.journal)).preflight()


def test_engine_kill_switch(tcfg):
    cfg = tcfg()
    b = FakeTrendBroker(_series())
    e = TrendEngine(cfg, b, Journal(cfg.journal))
    e.step()
    cfg.kill_switch_file.touch()
    e.step()
    assert e.stopped and not any(b.positions.values())


def test_engine_skips_asset_with_data_error(tcfg):
    cfg = tcfg()
    b = FakeTrendBroker(_series())
    b.positions["SXR8"] = 3.0
    orig = b.daily_bars
    b.daily_bars = lambda inst, n: (_ for _ in ()).throw(RuntimeError("no data")) \
        if inst.symbol == "SXR8" else orig(inst, n)
    e = TrendEngine(cfg, b, Journal(cfg.journal))
    e.step()
    assert b.positions["SXR8"] == 3.0  # untouched, not sold on missing data
    assert "no data, skipped" in cfg.journal.read_text()


def test_fx_quantity_uses_quote_currency(tcfg):
    cfg = tcfg()
    b = FakeTrendBroker(_series(), rates={("EUR", "USD"): 1.1})
    e = TrendEngine(cfg, b, Journal(cfg.journal))
    e.step()
    eur_notional = abs(b.positions["EURUSD"]) * b.series["EURUSD"][-1].close / 1.1
    assert 0 < eur_notional <= 0.8 * 10_000 + 1  # within max_weight of equity


def test_paper_mode_refuses_real_account(tcfg):
    cfg = tcfg()
    with pytest.raises(RuntimeError, match="non-paper"):
        TrendEngine(cfg, FakeTrendBroker(_series(), account="U1"), Journal(None)).preflight()


# --- backtest --------------------------------------------------------------
def test_backtest_profits_on_persistent_trends_and_pays_costs(tcfg):
    cfg = tcfg()
    data = {"EURUSD": daily(trending(400, 1.1, -0.0008)), "SXR8": daily(trending(400, 400, 0.0008))}
    res = run_trend_backtest(data, cfg)
    assert res["cagr_pct"] > 0 and res["trades"] > 0 and res["costs_paid"] > 0
    assert res["avg_gross_exposure"] <= 1.5 + 1e-9


def test_backtest_no_lookahead(tcfg):
    """A one-day jump on the final day must not be captured (signal uses prior closes)."""
    cfg = tcfg()
    flat = [100.0] * 60
    data = {"SXR8": daily(flat + [150.0])}
    res = run_trend_backtest(data, cfg)
    assert 9_990 < res["final_equity"] <= 10_000  # no +50% windfall; only the entry cost
