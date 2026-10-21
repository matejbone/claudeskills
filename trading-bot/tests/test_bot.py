from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from conftest import FakeBroker, make_bars, wave

from bot.backtest import run_backtest
from bot.config import RiskConfig, load_config
from bot.engine import Engine
from bot.journal import Journal
from bot.models import Action, Instrument, Market
from bot.risk import RiskManager
from bot.strategies import build_strategy
from bot.strategies.ema_cross import EmaCross

STOCK = Instrument("SPY", Market.STOCKS, "SMART")
COIN = Instrument("BTC", Market.CRYPTO, "PAXOS", qty_decimals=4)


# --- config safety ---------------------------------------------------------
def test_paper_config_loads(write_config):
    cfg = load_config(write_config())
    assert cfg.mode == "paper" and {i.symbol for i in cfg.instruments} == {"SPY", "BTC"}


def test_live_requires_env_and_live_port(write_config):
    text = write_config().read_text().replace("mode: paper", "mode: live")
    with pytest.raises(ValueError, match="TRADING_BOT_LIVE"):
        load_config(write_config(text=text), env={})
    with pytest.raises(ValueError, match="paper-trading port"):
        load_config(write_config(text=text), env={"TRADING_BOT_LIVE": "yes"})
    cfg = load_config(write_config(text=text.replace("port: 7497", "port: 7496")),
                      env={"TRADING_BOT_LIVE": "yes"})
    assert cfg.live


def test_paper_mode_rejects_live_port(write_config):
    text = write_config().read_text().replace("port: 7497", "port: 7496")
    with pytest.raises(ValueError, match="not a paper port"):
        load_config(write_config(text=text), env={})


def test_excessive_risk_refused():
    with pytest.raises(ValueError):
        RiskConfig(risk_per_trade_pct=10)


# --- strategy --------------------------------------------------------------
def test_ema_cross_signals():
    s = EmaCross(fast=3, slow=6, atr_period=3)
    sig = s.signal(make_bars([100.0] * 22 + [101]), in_position=False)
    assert sig and sig.action is Action.BUY and sig.stop < 101 < sig.target
    assert s.signal(make_bars([100.0] * 22 + [101]), in_position=True) is None
    assert s.signal(make_bars([100.0] * 22 + [99]), in_position=True).action is Action.EXIT
    assert s.signal(make_bars([100.0] * 10), in_position=False) is None  # warmup


def test_unknown_strategy():
    with pytest.raises(ValueError, match="unknown strategy"):
        build_strategy("nope")


# --- risk ------------------------------------------------------------------
def test_sizing_caps_and_rounding():
    r = RiskManager(RiskConfig(risk_per_trade_pct=1, max_position_pct=20))
    assert r.size(STOCK, 10_000, 100, 99) == 20  # 1% risk -> 100 sh, capped at 20% notional
    assert r.size(STOCK, 10_000, 100, 90) == 10  # 1% risk -> 10 sh
    assert r.size(COIN, 10_000, 60_000, 59_000) == 0.0333  # capped, floored to 4 dp
    assert r.size(STOCK, 10_000, 100, 101) == 0  # stop above entry
    assert r.size(STOCK, 10_000, 100, 99.95) == 0  # stop tighter than min_stop_pct


def test_circuit_breaker_and_daily_reset(tmp_path):
    r = RiskManager(RiskConfig(max_daily_loss_pct=2), tmp_path / "s.json")
    r.start_day(date(2026, 10, 19), 10_000)
    assert not r.update_equity(9_850)
    assert r.update_equity(9_790)
    assert not r.can_open(STOCK, 0, 9_790, date(2026, 10, 19))[0]
    # persisted across restart
    assert RiskManager(RiskConfig(), tmp_path / "s.json").state.halted
    r.start_day(date(2026, 10, 20), 9_790)
    assert not r.state.halted


def test_pdt_guard():
    r = RiskManager(RiskConfig(max_trades_per_day=50))
    today = date(2026, 10, 21)
    for d in (date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)):
        r.record_day_trade(d)
    assert r.can_open(STOCK, 0, 10_000, today) == (False, "PDT guard: 3 day trades in last 5 business days")
    assert r.can_open(COIN, 0, 10_000, today)[0]       # crypto unaffected
    assert r.can_open(STOCK, 0, 30_000, today)[0]      # above $25k unaffected


# --- engine ----------------------------------------------------------------
def _engine(cfg_path, broker):
    cfg = load_config(cfg_path)
    return Engine(cfg, broker, build_strategy(cfg.strategy_name, cfg.strategy_params),
                  RiskManager(cfg.risk, cfg.state_file, cfg.pdt_guard), Journal(cfg.journal))


def _entry_series():
    return make_bars([100.0] * 22 + [101])


def test_engine_enters_then_stops_out(write_config):
    bars = _entry_series()
    b = FakeBroker({"SPY": bars, "BTC": make_bars([100.0] * 23)})
    e = _engine(write_config(), b)
    e.preflight()
    e.step()
    assert b.orders[0][0] == "BUY" and "stocks:SPY" in e.trades
    stop = e.trades["stocks:SPY"].stop
    b.series["SPY"] = bars + make_bars([stop - 1], start=bars[-1].ts + timedelta(minutes=5))
    b.idx["SPY"] += 1
    e.step()
    assert b.orders[-1][0] == "SELL" and not e.trades
    assert "stop" in e.cfg.journal.read_text()


def test_engine_refuses_real_account_in_paper_mode(write_config):
    e = _engine(write_config(), FakeBroker({"SPY": _entry_series(), "BTC": _entry_series()}, account="U999"))
    with pytest.raises(RuntimeError, match="non-paper account"):
        e.preflight()


def test_engine_kill_switch_flattens(write_config):
    b = FakeBroker({"SPY": _entry_series(), "BTC": make_bars([100.0] * 23)})
    cfg_path = write_config()
    e = _engine(cfg_path, b)
    e.step()
    assert b.positions
    (cfg_path.parent / "STOP").touch()
    e.step()
    assert not b.positions and e.stopped


def test_engine_circuit_breaker_flattens_and_blocks(write_config):
    b = FakeBroker({"SPY": _entry_series(), "BTC": make_bars([100.0] * 23)})
    e = _engine(write_config(), b)
    e.step()
    assert b.positions
    b._equity = 9_700  # -3% on the day
    e.step()
    assert not b.positions and e.risk.state.halted
    assert "HALT" in e.cfg.journal.read_text()


def test_engine_no_stock_entries_outside_session(write_config):
    early = datetime(2026, 10, 19, 13, 35, tzinfo=timezone.utc)  # 09:35 ET
    b = FakeBroker({"SPY": _entry_series(), "BTC": _entry_series()}, now=early)
    e = _engine(write_config(), b)
    e.step()
    assert "SPY" not in b.positions and "BTC" in b.positions  # crypto trades 24/7


def test_engine_flattens_stocks_at_end_of_day(write_config):
    b = FakeBroker({"SPY": _entry_series(), "BTC": make_bars([100.0] * 23)})
    e = _engine(write_config(), b)
    e.step()
    b._now = datetime(2026, 10, 19, 19, 55, tzinfo=timezone.utc)  # 15:55 ET
    e.step()
    assert "SPY" not in b.positions
    assert e.risk.day_trades_last_5(date(2026, 10, 19)) == 1


def test_engine_resumes_open_trades_after_restart(write_config):
    b = FakeBroker({"SPY": _entry_series(), "BTC": make_bars([100.0] * 23)})
    cfg_path = write_config()
    _engine(cfg_path, b).step()
    assert "stocks:SPY" in _engine(cfg_path, b).trades


# --- backtest --------------------------------------------------------------
def test_backtest_runs_and_reports():
    start = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    bars = make_bars(wave(600, amp=15), start=start)
    res = run_backtest(bars, COIN, EmaCross(fast=5, slow=15), RiskConfig(), 10_000)
    assert res["num_trades"] > 0
    assert 0 <= res["max_drawdown_pct"] < 100
    assert len(res["equity_curve"]) >= len(bars) - EmaCross(fast=5, slow=15).warmup
    for t in res["trades"]:
        assert t.exit_ts >= t.entry_ts and t.exit_ts - t.entry_ts < timedelta(days=30)
