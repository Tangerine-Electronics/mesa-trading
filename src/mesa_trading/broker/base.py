"""Interfaz que tendría un broker real. En este repo solo la implementa SimBroker."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from mesa_trading.models import Ack, Fill, Order


class Broker(ABC):
    @abstractmethod
    def submit(self, order: Order) -> Ack:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def cancel(self, client_order_id: str) -> None:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def fills(self, since: datetime | None = None) -> list[Fill]:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def positions(self) -> list[dict]:
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def balance(self) -> Decimal:
        raise NotImplementedError  # pragma: no cover
