from __future__ import annotations

from bot.strategies.base import Strategy
from bot.strategies.ema_cross import EmaCross

# Register new strategies here: name -> class.
REGISTRY: dict[str, type[Strategy]] = {
    EmaCross.name: EmaCross,
}


def build_strategy(name: str, params: dict | None = None) -> Strategy:
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown strategy {name!r}; available: {sorted(REGISTRY)}") from None
    return cls(**(params or {}))
