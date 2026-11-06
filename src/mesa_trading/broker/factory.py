"""make_broker solo acepta shadow y simulated. Cualquier otro modo aborta."""

from __future__ import annotations

from mesa_trading.broker.base import Broker
from mesa_trading.broker.sim import SimBroker


class ShadowGate:
    """Modo sombra: no es un Broker y no crea órdenes."""

    def __init__(self) -> None:
        self.noted: list[dict] = []

    def note(self, intent: dict) -> None:
        self.noted.append(intent)

    def submit(self, order) -> None:
        raise RuntimeError("modo sombra: no se crean órdenes")


def make_broker(mode: str, **kwargs) -> Broker | ShadowGate:
    if mode == "shadow":
        return ShadowGate()
    if mode == "simulated":
        return SimBroker(**kwargs)
    raise ValueError(f"modo de broker no permitido: {mode}")
