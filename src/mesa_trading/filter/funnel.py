"""Embudo: primero lo barato. No operar es un resultado y queda registrado."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from mesa_trading.util import as_utc

COOLDOWNS = {
    "spread_ancho": timedelta(minutes=15),
    "sin_libro": timedelta(minutes=5),
    "liquidez_baja": timedelta(minutes=15),
    "mercado_cerrado": timedelta(minutes=30),
    "datos_viejos": timedelta(minutes=5),
    "volatilidad_extrema": timedelta(minutes=15),
    "economia": timedelta(minutes=15),
    "contrato_peligroso": None,
}


@dataclass(frozen=True)
class FilterResult:
    step: str
    reason: str | None

    @property
    def rejected(self) -> bool:
        return self.reason is not None


def hard(
    snapshot: dict,
    *,
    market_open: bool = True,
    max_age_s: int = 600,
    max_spread_bps: Decimal = Decimal("25"),
    min_liquidity_usd: Decimal = Decimal("10000"),
) -> FilterResult:
    step = "hechos_duros"
    if not market_open:
        return FilterResult(step, "mercado_cerrado")
    age = snapshot.get("age_s")
    if age is None or int(age) > max_age_s:
        return FilterResult(step, "datos_viejos")
    spread = snapshot.get("spread_bps")
    # Sin bid/ask no es un spread ancho: es un libro que no llegó. Se cuenta aparte.
    if spread is None:
        return FilterResult(step, "sin_libro")
    if Decimal(str(spread)) > max_spread_bps:
        return FilterResult(step, "spread_ancho")
    liquidity = snapshot.get("liquidity_usd")
    if liquidity is None or Decimal(str(liquidity)) < min_liquidity_usd:
        return FilterResult(step, "liquidez_baja")
    flags = snapshot.get("token_flags") or {}
    if flags.get("honeypot") or flags.get("mint_authority_open") or flags.get("liquidity_locked") is False:
        return FilterResult(step, "contrato_peligroso")
    return FilterResult(step, None)


def cheap(
    snapshot: dict,
    *,
    notional_usd: Decimal,
    min_fee_usd: Decimal,
    max_vol: Decimal = Decimal("0.05"),
    max_fee_fraction: Decimal = Decimal("0.02"),
) -> FilterResult:
    step = "calculos_baratos"
    vol = snapshot.get("vol")
    if vol is not None and Decimal(str(vol)) > max_vol:
        return FilterResult(step, "volatilidad_extrema")
    if notional_usd > 0 and min_fee_usd >= notional_usd * max_fee_fraction:
        return FilterResult(step, "economia")
    return FilterResult(step, None)


def bank_until(reason: str, now: datetime) -> datetime | None:
    cool = COOLDOWNS.get(reason, timedelta(minutes=15))
    if cool is None:
        return None
    return as_utc(now) + cool


def still_banked(until: str | None, now: datetime) -> bool:
    if until is None:
        return False
    if until == "permanent":
        return True
    return as_utc(datetime.fromisoformat(until.replace("Z", "+00:00"))) > as_utc(now)


def silent_step_alerts(reached: dict[str, int], rejected: dict[str, int]) -> list[str]:
    alerts = []
    for step, count in reached.items():
        if count >= 50 and rejected.get(step, 0) == 0:
            alerts.append(f"filtro_mudo:{step}")
    return alerts
