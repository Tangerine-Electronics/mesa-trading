"""Elige directorio local o el bucket según MESA_BUCKET."""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from mesa_trading.book.store import FileBookStore
from mesa_trading.logs.sink import FileLogSink, LogSink
from mesa_trading.book.store import BookStore


def open_logs(data_dir: str) -> LogSink:
    if os.environ.get("MESA_BUCKET"):
        from mesa_trading.gcs import GcsLogSink

        return GcsLogSink(os.environ["MESA_BUCKET"])
    return FileLogSink(Path(data_dir) / "logs")


def open_book(data_dir: str, capital: Decimal, now: datetime) -> BookStore:
    if os.environ.get("MESA_BUCKET"):
        from mesa_trading.gcs import GcsBookStore

        return GcsBookStore(os.environ["MESA_BUCKET"], capital, now)
    return FileBookStore(Path(data_dir) / "book", capital=capital, now=now)
