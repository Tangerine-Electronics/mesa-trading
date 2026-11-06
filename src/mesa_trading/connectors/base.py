"""Interfaz de mercado. Spy deja WalletSource y TokenFlagsSource sin implementación en F1."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class MarketConnector(Protocol):
    name: str

    def candles(self, symbol: str, interval: str, since: datetime | None = None) -> list[dict]: ...

    def order_book(self, symbol: str, depth: int = 5) -> dict | None: ...

    def trades(self, symbol: str, since: datetime | None = None) -> list[dict]: ...

    def funding(self, symbol: str) -> dict | None: ...

    def market_status(self) -> dict: ...

    def metadata(self) -> dict: ...


class WalletSource(Protocol):
    def history(self, address: str) -> dict: ...


class TokenFlagsSource(Protocol):
    def flags(self, token: str) -> dict: ...
