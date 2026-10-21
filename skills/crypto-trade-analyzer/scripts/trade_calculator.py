#!/usr/bin/env python3
"""Deterministic educational crypto trade calculations for Crypto Trade Analyzer (adapted from Crypto Spot & Futures Analyzer, MIT).

No market data is fetched. All values must be supplied by the caller.
"""
import argparse
import json


def position_size(account, risk_pct, entry, stop, leverage=1.0, side="long"):
    if min(account, risk_pct, entry, stop, leverage) <= 0:
        raise ValueError("All numeric inputs must be positive")
    risk_capital = account * (risk_pct / 100.0)
    if side == "long":
        stop_fraction = (entry - stop) / entry
    else:
        stop_fraction = (stop - entry) / entry
    if stop_fraction <= 0:
        raise ValueError("Stop must be below entry for long and above entry for short")
    notional = risk_capital / stop_fraction
    quantity = notional / entry
    margin = notional / leverage
    return {
        "risk_capital": risk_capital,
        "stop_distance_pct": stop_fraction * 100,
        "position_notional": notional,
        "position_quantity": quantity,
        "approx_margin": margin,
    }


def pnl(entry, exit_price, quantity, side="long", fee_rate_pct=0.0, funding=0.0):
    if min(entry, exit_price, quantity) <= 0:
        raise ValueError("Entry, exit and quantity must be positive")
    gross = quantity * ((exit_price - entry) if side == "long" else (entry - exit_price))
    entry_notional = quantity * entry
    exit_notional = quantity * exit_price
    fees = (entry_notional + exit_notional) * (fee_rate_pct / 100.0)
    net = gross - fees - funding
    return {
        "gross_pnl": gross,
        "estimated_fees": fees,
        "estimated_funding": funding,
        "net_pnl": net,
        "return_on_entry_notional_pct": (net / entry_notional) * 100,
    }


def rr(entry, stop, target, side="long"):
    if side == "long":
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target
    if risk <= 0 or reward <= 0:
        raise ValueError("Invalid stop/target geometry for selected side")
    return {"risk": risk, "reward": reward, "reward_to_risk": reward / risk}


def dca(prices, amounts):
    if len(prices) != len(amounts) or not prices:
        raise ValueError("Prices and amounts must be non-empty and equal length")
    if any(p <= 0 for p in prices) or any(a <= 0 for a in amounts):
        raise ValueError("Prices and amounts must be positive")
    quantities = [a / p for p, a in zip(prices, amounts)]
    total_cost = sum(amounts)
    total_qty = sum(quantities)
    return {"total_cost": total_cost, "total_quantity": total_qty, "average_entry": total_cost / total_qty}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("position-size")
    p.add_argument("--account", type=float, required=True)
    p.add_argument("--risk-pct", type=float, required=True)
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--leverage", type=float, default=1.0)
    p.add_argument("--side", choices=["long", "short"], default="long")

    p = sub.add_parser("pnl")
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--exit", dest="exit_price", type=float, required=True)
    p.add_argument("--quantity", type=float, required=True)
    p.add_argument("--side", choices=["long", "short"], default="long")
    p.add_argument("--fee-rate-pct", type=float, default=0.0)
    p.add_argument("--funding", type=float, default=0.0)

    p = sub.add_parser("rr")
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--target", type=float, required=True)
    p.add_argument("--side", choices=["long", "short"], default="long")

    p = sub.add_parser("dca")
    p.add_argument("--prices", type=float, nargs="+", required=True)
    p.add_argument("--amounts", type=float, nargs="+", required=True)

    args = parser.parse_args()
    if args.cmd == "position-size":
        out = position_size(args.account, args.risk_pct, args.entry, args.stop, args.leverage, args.side)
    elif args.cmd == "pnl":
        out = pnl(args.entry, args.exit_price, args.quantity, args.side, args.fee_rate_pct, args.funding)
    elif args.cmd == "rr":
        out = rr(args.entry, args.stop, args.target, args.side)
    else:
        out = dca(args.prices, args.amounts)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
