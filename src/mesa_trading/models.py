"""Tipos compartidos de la mesa. El dinero es Decimal, nunca float de negocio."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    cycle_id: str
    bot: str
    market: str
    side: Literal["buy", "sell"]
    action: str
    order_type: Literal["market", "limit"]
    qty: Decimal
    notional_usd: Decimal
    limit_price: Decimal | None = None
    decision_time: datetime
    reason: str = ""
    leverage: Decimal = Decimal("1")
    kind: Literal["spot", "perp"] = "spot"


class Ack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    accepted: bool
    detail: str = ""


class Fill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_order_id: str
    market: str
    side: Literal["buy", "sell"]
    qty: Decimal
    price: Decimal
    fee_usd: Decimal
    slippage_usd: Decimal
    gas_usd: Decimal
    filled_at: datetime
    price_source: str
    reason: str = ""


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: str
    bot: str
    side: Literal["long", "short"]
    qty: Decimal
    entry_price: Decimal
    notional_usd: Decimal
    opened_at: datetime
    fees_usd: Decimal = Decimal("0")
    slippage_usd: Decimal = Decimal("0")
    kind: Literal["spot", "perp"] = "spot"


class BookState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cash_usd: Decimal
    day_start_equity_usd: Decimal
    day_start_utc: str
    realized_pnl_usd: Decimal = Decimal("0")
    day_realized_pnl_usd: Decimal = Decimal("0")
    fees_usd: Decimal = Decimal("0")
    slippage_usd: Decimal = Decimal("0")
    peak_equity_usd: Decimal
    position: Position | None = None
    halted_until: datetime | None = None
    halt_rule: str | None = None
    last_prices: dict[str, str] = Field(default_factory=dict)
    bank: dict[str, str] = Field(default_factory=dict)
    seen_orders: list[str] = Field(default_factory=list)
    equity_hwm_usd: Decimal | None = None
    # Resultados por resolver, sin releer toda la bitácora en cada ciclo.
    pending_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    last_cycle_id: str | None = None
    last_cycle_at: str | None = None
    closed_trades: int = 0
    started_at: str | None = None


class Proposal(BaseModel):
    """Acción que sale de la política. Sin probabilidades: el riesgo no las lee."""

    model_config = ConfigDict(extra="forbid")

    bot: str
    market: str
    action: Literal["long", "short", "hold", "quote", "pause", "mirror", "skip", "close"]
    notional_usd: Decimal = Decimal("0")
    leverage: Decimal = Decimal("1")
    kind: Literal["spot", "perp"] = "spot"
    threshold_version: int
    thresholds: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    is_entry: bool = False


class Veto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str
    detail: str
    halt: bool = False
    close_position: bool = False
