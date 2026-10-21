from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

import yaml

from bot.config import OperatingHours, _t, check_mode, parse_operating_hours
from bot.models import Instrument, Market


@dataclass(frozen=True)
class Asset:
    inst: Instrument
    long_only: bool
    cost_pct: float      # estimated commission + spread per side, % of notional
    min_order: float     # skip trades smaller than this, in account currency


@dataclass(frozen=True)
class TrendConfig:
    mode: str
    ib_host: str
    ib_port: int
    ib_client_id: int
    account_currency: str
    operating_hours: OperatingHours | None
    rebalance_time: time
    assets: list[Asset]
    lookbacks: list[int]
    vol_window: int
    target_vol_pct: float
    max_weight: float
    max_gross: float
    rebalance_threshold: float
    max_drawdown_pct: float
    poll_seconds: int
    journal: Path
    state_file: Path
    kill_switch_file: Path
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @property
    def long_only(self) -> set[str]:
        return {a.inst.symbol for a in self.assets if a.long_only}


def load_trend_config(path: str | Path, env: dict | None = None) -> TrendConfig:
    env = os.environ if env is None else env
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    base = path.parent
    mode = raw.get("mode", "paper")
    ib = raw.get("ib", {})
    port = int(ib.get("port", 7497))
    check_mode(mode, port, env)

    assets = []
    for a in raw.get("assets", []):
        market = Market(a["market"])
        if market is Market.CRYPTO:
            raise ValueError("crypto is not supported in trend mode (IB crypto fees and no shorting)")
        assets.append(Asset(
            inst=Instrument(a["symbol"], market, a.get("exchange", "IDEALPRO" if market is Market.FOREX
                                                         else "SMART"),
                            a.get("currency", "USD"), int(a.get("qty_decimals", 0)),
                            a.get("primary_exchange", "")),
            long_only=bool(a.get("long_only", market is not Market.FOREX)),
            cost_pct=float(a.get("cost_pct", 0.01 if market is Market.FOREX else 0.1)),
            min_order=float(a.get("min_order", 1000)),
        ))
    if not assets:
        raise ValueError("no assets configured")
    if len({a.inst.symbol for a in assets}) != len(assets):
        raise ValueError("duplicate asset symbols")

    s = raw.get("strategy", {}) or {}
    r = raw.get("risk", {}) or {}
    cfg = TrendConfig(
        mode=mode,
        ib_host=ib.get("host", "127.0.0.1"),
        ib_port=port,
        ib_client_id=int(ib.get("client_id", 18)),
        account_currency=raw.get("account_currency", "EUR"),
        operating_hours=parse_operating_hours(raw.get("operating_hours")),
        rebalance_time=_t(raw.get("rebalance_time", "09:30")),
        assets=assets,
        lookbacks=[int(x) for x in s.get("lookbacks", [21, 63, 126, 252])],
        vol_window=int(s.get("vol_window", 60)),
        target_vol_pct=float(r.get("target_vol_pct", 8)),
        max_weight=float(r.get("max_weight_per_asset", 0.5)),
        max_gross=float(r.get("max_gross_exposure", 1.5)),
        rebalance_threshold=float(r.get("rebalance_threshold", 0.25)),
        max_drawdown_pct=float(r.get("max_drawdown_pct", 20)),
        poll_seconds=int(raw.get("poll_seconds", 60)),
        journal=base / raw.get("journal", "trend_journal.csv"),
        state_file=base / raw.get("state_file", "trend_state.json"),
        kill_switch_file=base / raw.get("kill_switch_file", "STOP"),
        raw=raw,
    )
    if not 0 < cfg.target_vol_pct <= 20:
        raise ValueError("risk.target_vol_pct must be in (0, 20]")
    if not 0 < cfg.max_gross <= 3:
        raise ValueError("risk.max_gross_exposure must be in (0, 3]")
    if not 0 < cfg.max_drawdown_pct <= 50:
        raise ValueError("risk.max_drawdown_pct must be in (0, 50]")
    oh = cfg.operating_hours
    if oh and not oh.start <= cfg.rebalance_time < oh.last_entry:
        raise ValueError("rebalance_time must be inside operating_hours start..last_entry")
    return cfg
