"""Command line:

  python -m bot backtest --config config.yaml --csv data/SPY_5m.csv --symbol SPY
  python -m bot download --config config.yaml --symbol SPY --out data/SPY_5m.csv
  python -m bot run      --config config.yaml
"""
from __future__ import annotations

import argparse
import json
import logging

from bot.backtest import load_csv, run_backtest, save_csv, write_trades
from bot.config import load_config
from bot.journal import Journal
from bot.risk import RiskManager
from bot.strategies import build_strategy


def _instrument(cfg, symbol):
    for inst in cfg.instruments:
        if inst.symbol == symbol:
            return inst
    raise SystemExit(f"{symbol} is not an enabled symbol in the config")


def _ib(cfg):
    from bot.broker.ib import IBBroker

    return IBBroker(cfg.ib_host, cfg.ib_port, cfg.ib_client_id, cfg.bar_size, cfg.risk.slippage_pct)


def cmd_backtest(args):
    cfg = load_config(args.config)
    inst = _instrument(cfg, args.symbol)
    strat = build_strategy(cfg.strategy_name, cfg.strategy_params)
    res = run_backtest(load_csv(args.csv), inst, strat, cfg.risk, args.equity, cfg.stock_session)
    if args.trades_out:
        write_trades(res["trades"], args.trades_out)
    print(json.dumps({k: v for k, v in res.items() if k not in ("trades", "equity_curve")}, indent=2))


def cmd_download(args):
    cfg = load_config(args.config)
    broker = _ib(cfg)
    broker.connect()
    try:
        bars = broker.bars(_instrument(cfg, args.symbol), 100_000)
    finally:
        broker.disconnect()
    save_csv(bars, args.out)
    print(f"saved {len(bars)} bars to {args.out}")


def cmd_run(args):
    from bot.engine import Engine

    cfg = load_config(args.config)
    broker = _ib(cfg)
    engine = Engine(cfg, broker, build_strategy(cfg.strategy_name, cfg.strategy_params),
                    RiskManager(cfg.risk, cfg.state_file, cfg.pdt_guard), Journal(cfg.journal))
    broker.connect()
    try:
        engine.preflight()
        while not engine.stopped:
            engine.step()
            broker.ib.sleep(cfg.poll_seconds)  # keeps ib_async's event loop running
    except KeyboardInterrupt:
        logging.getLogger("bot").info("Ctrl+C - open trades keep their broker-side stops (stocks); "
                                      "crypto trades are unprotected until the bot restarts")
    finally:
        broker.disconnect()


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="bot")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backtest")
    b.add_argument("--config", default="config.yaml")
    b.add_argument("--csv", required=True)
    b.add_argument("--symbol", required=True)
    b.add_argument("--equity", type=float, default=10_000)
    b.add_argument("--trades-out")
    b.set_defaults(func=cmd_backtest)

    d = sub.add_parser("download")
    d.add_argument("--config", default="config.yaml")
    d.add_argument("--symbol", required=True)
    d.add_argument("--out", required=True)
    d.set_defaults(func=cmd_download)

    r = sub.add_parser("run")
    r.add_argument("--config", default="config.yaml")
    r.set_defaults(func=cmd_run)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
