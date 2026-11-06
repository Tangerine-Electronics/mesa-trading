"""Tabla de comisiones. El costo de una orden sale de aquí, no del modelo."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from mesa_trading.config import default_fees_path


class FeeSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taker_bps: Decimal
    min_fee_usd: Decimal
    gas_usd: Decimal = Decimal("0")


def load_fees(path: Path | None = None) -> dict[str, FeeSchedule]:
    target = path or default_fees_path()
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return {name: FeeSchedule.model_validate(body) for name, body in raw.items()}


def commission_usd(notional: Decimal, schedule: FeeSchedule) -> Decimal:
    proportional = notional * schedule.taker_bps / Decimal("10000")
    if proportional < schedule.min_fee_usd:
        return schedule.min_fee_usd
    return proportional


def slippage_usd(notional: Decimal, spread_bps: Decimal, liquidity_usd: Decimal, extra_bps: Decimal) -> Decimal:
    """Medio spread + impacto proporcional al tamaño / liquidez + extra en bps."""
    half_spread = spread_bps / Decimal("2")
    if liquidity_usd <= 0:
        impact = Decimal("50")
    else:
        impact = (notional / liquidity_usd) * Decimal("10000")
    bps = half_spread + impact + extra_bps
    return notional * bps / Decimal("10000")


def total_cost_usd(
    notional: Decimal,
    schedule: FeeSchedule,
    spread_bps: Decimal,
    liquidity_usd: Decimal,
    extra_bps: Decimal = Decimal("1"),
) -> tuple[Decimal, Decimal, Decimal]:
    fee = commission_usd(notional, schedule)
    slip = slippage_usd(notional, spread_bps, liquidity_usd, extra_bps)
    return fee, slip, schedule.gas_usd
