"""Sobre mínimo de cada renglón de la bitácora."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mesa_trading.constants import SCHEMA_VERSION
from mesa_trading.util import event_id, iso


def make_event(
    event_type: str,
    *,
    cycle_id: str,
    occurred_at: datetime,
    bot: str = "",
    mode: str = "",
    causation_id: str = "",
    payload: dict[str, Any] | None = None,
    parts: tuple[str, ...] = (),
) -> dict[str, Any]:
    body = payload or {}
    return {
        "event_id": event_id(cycle_id, event_type, bot, mode, *parts),
        "event_type": event_type,
        "schema_version": SCHEMA_VERSION,
        "occurred_at": iso(occurred_at),
        "correlation_id": cycle_id,
        "causation_id": causation_id,
        "bot": bot,
        "mode": mode,
        "payload": body,
    }
