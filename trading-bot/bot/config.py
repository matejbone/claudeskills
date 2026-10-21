from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from bot.models import Instrument, Market

LIVE_ENV = "TRADING_BOT_LIVE"
PAPER_PORTS = {7497, 4002}


@dataclass(frozen=True)
class Session:
    tz: ZoneInfo
    start: time
    last_entry: time
    flatten: time


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 0.5
    max_position_pct: float = 20.0
    max_daily_loss_pct: float = 2.0
    max_open_positions: int = 2
    max_trades_per_day: int = 10
    min_stop_pct: float = 0.15
    slippage_pct: float = 0.05
    fee_pct: float = 0.02

    def __post_init__(self):
        for name in ("risk_per_trade_pct", "max_position_pct", "max_daily_loss_pct"):
            v = getattr(self, name)
            if not 0 < v <= 100:
                raise ValueError(f"risk.{name} must be in (0, 100], got {v}")
        if self.risk_per_trade_pct > 5:
            raise ValueError("risk.risk_per_trade_pct above 5% is refused")
        if self.max_open_positions < 1 or self.max_trades_per_day < 1:
            raise ValueError("risk limits must be at least 1")


@dataclass(frozen=True)
class Config:
    mode: str
    ib_host: str
    ib_port: int
    ib_client_id: int
    bar_size: str
    poll_seconds: int
    strategy_name: str
    strategy_params: dict
    instruments: list[Instrument]
    stock_session: Session | None
    pdt_guard: bool
    risk: RiskConfig
    journal: Path
    state_file: Path
    kill_switch_file: Path
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def live(self) -> bool:
        return self.mode == "live"


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def load_config(path: str | Path, env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    base = path.parent

    mode = raw.get("mode", "paper")
    if mode not in ("paper", "live"):
        raise ValueError("mode must be 'paper' or 'live'")
    ib = raw.get("ib", {})
    port = int(ib.get("port", 7497))

    # Live trading needs two independent switches so it can't happen by accident.
    if mode == "live":
        if env.get(LIVE_ENV) != "yes":
            raise ValueError(f"mode: live also requires the environment variable {LIVE_ENV}=yes")
        if port in PAPER_PORTS:
            raise ValueError(f"mode: live but port {port} is a paper-trading port")
    elif port not in PAPER_PORTS:
        raise ValueError(f"mode: paper but port {port} is not a paper port {sorted(PAPER_PORTS)}")

    instruments: list[Instrument] = []
    session = None
    pdt_guard = False
    markets = raw.get("markets", {})
    for mname, mcfg in markets.items():
        market = Market(mname)
        if not mcfg.get("enabled", True):
            continue
        for sym in mcfg.get("symbols", []):
            instruments.append(Instrument(
                symbol=sym, market=market, exchange=mcfg.get("exchange", "SMART"),
                currency=mcfg.get("currency", "USD"), qty_decimals=int(mcfg.get("qty_decimals", 0)),
            ))
        if market is Market.STOCKS:
            s = mcfg.get("session", {})
            session = Session(
                tz=ZoneInfo(s.get("tz", "America/New_York")),
                start=_t(s.get("start", "09:45")),
                last_entry=_t(s.get("last_entry", "15:30")),
                flatten=_t(s.get("flatten", "15:50")),
            )
            pdt_guard = bool(mcfg.get("pdt_guard", True))
    if not instruments:
        raise ValueError("no instruments enabled")

    strat = raw.get("strategy", {})
    return Config(
        mode=mode,
        ib_host=ib.get("host", "127.0.0.1"),
        ib_port=port,
        ib_client_id=int(ib.get("client_id", 17)),
        bar_size=raw.get("bar_size", "5 mins"),
        poll_seconds=int(raw.get("poll_seconds", 60)),
        strategy_name=strat.get("name", "ema_cross"),
        strategy_params=strat.get("params", {}) or {},
        instruments=instruments,
        stock_session=session,
        pdt_guard=pdt_guard,
        risk=RiskConfig(**(raw.get("risk") or {})),
        journal=base / raw.get("journal", "journal.csv"),
        state_file=base / raw.get("state_file", "state.json"),
        kill_switch_file=base / raw.get("kill_switch_file", "STOP"),
        raw=raw,
    )
