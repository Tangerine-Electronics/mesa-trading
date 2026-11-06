"""Conector de datos grabados. Las pruebas no salen a la red."""

from __future__ import annotations

from datetime import datetime


class FixtureConnector:
    name = "fixture"

    def __init__(
        self,
        candles: dict[str, list[dict]] | None = None,
        books: dict[str, dict] | None = None,
        funding: dict[str, dict] | None = None,
        fail_times: int = 0,
    ) -> None:
        self._candles = candles or {}
        self._books = books or {}
        self._funding = funding or {}
        self.fail_times = fail_times
        self.calls = 0

    def candles(self, symbol: str, interval: str, since: datetime | None = None) -> list[dict]:
        self._maybe_fail()
        rows = list(self._candles.get(symbol, []))
        if since is None:
            return rows
        return [row for row in rows if row["ts"] >= since]

    def order_book(self, symbol: str, depth: int = 5) -> dict | None:
        self._maybe_fail()
        return self._books.get(symbol)

    def trades(self, symbol: str, since: datetime | None = None) -> list[dict]:
        return []

    def funding(self, symbol: str) -> dict | None:
        return self._funding.get(symbol)

    def market_status(self) -> dict:
        return {"open": True}

    def metadata(self) -> dict:
        return {"name": self.name}

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("sin datos")
