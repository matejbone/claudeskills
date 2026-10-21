from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("bot")

FIELDS = ["ts", "event", "symbol", "qty", "price", "stop", "target", "pnl", "note"]


class Journal:
    """Append-only CSV of everything the bot does, for review and post-mortems."""

    def __init__(self, path: Path | None):
        self.path = path
        if path and not path.exists():
            with path.open("w", newline="") as f:
                csv.writer(f).writerow(FIELDS)

    def write(self, ts: datetime, event: str, symbol: str = "", qty=None, price=None,
              stop=None, target=None, pnl=None, note: str = "") -> None:
        row = [ts.isoformat(), event, symbol, qty, price, stop, target, pnl, note]
        log.info("%s %s %s qty=%s price=%s stop=%s target=%s pnl=%s %s", *row)
        if self.path:
            with self.path.open("a", newline="") as f:
                csv.writer(f).writerow(["" if v is None else v for v in row])
