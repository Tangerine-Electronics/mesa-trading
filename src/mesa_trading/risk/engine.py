"""Vetos duros. No leen probabilidades del modelo. Ninguna respuesta los salta."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from mesa_trading.broker.fees import FeeSchedule, total_cost_usd
from mesa_trading.config import DeskConfig
from mesa_trading.models import BookState, Proposal, Veto


class RiskFacts(BaseModel):
    """Hechos calculados en código. Sin respuestas de Jev."""

    model_config = ConfigDict(extra="forbid")

    snapshot_age_s: int | None
    max_age_s: int
    model_version_ok: bool = True
    spread_bps: Decimal = Decimal("2")
    liquidity_usd: Decimal = Decimal("1000000")
    fee_schedule: FeeSchedule = FeeSchedule(taker_bps=Decimal("60"), min_fee_usd=Decimal("0"), gas_usd=Decimal("0"))
    expected_edge_bps: Decimal = Decimal("8")
    extra_bps: Decimal = Decimal("1")
    price: Decimal | None = None
    range_low: Decimal | None = None
    range_high: Decimal | None = None
    volume_ratio: Decimal | None = None
    equity_usd: Decimal = Decimal("1000")
    day_pnl_usd: Decimal = Decimal("0")


def evaluate(proposal: Proposal, book: BookState, facts: RiskFacts, config: DeskConfig) -> Veto | None:
    if facts.snapshot_age_s is None or facts.snapshot_age_s > facts.max_age_s:
        return Veto(rule="datos_viejos", detail="el snapshot supera la edad máxima")
    if not facts.model_version_ok:
        return Veto(rule="version_modelo", detail="la versión devuelta no es la fijada")
    if proposal.leverage != Decimal("1") or config.risk.leverage != Decimal("1"):
        return Veto(rule="apalancamiento", detail="solo 1x")
    if proposal.action == "short" and proposal.kind == "spot":
        return Veto(rule="corto_spot", detail="en spot, corto significa no entrar")

    day_limit = book.day_start_equity_usd * config.risk.daily_loss_pct
    if facts.day_pnl_usd <= -day_limit:
        return Veto(rule="perdida_diaria", detail="pérdida del día alcanzó el límite", halt=True)

    if proposal.action in {"long", "short", "quote"} and proposal.is_entry:
        if config.risk.single_position and book.position is not None:
            return Veto(rule="exposicion_total", detail="ya hay una posición en la mesa")
        cap = facts.equity_usd * config.risk.max_position_pct
        if proposal.notional_usd > cap:
            return Veto(rule="posicion_maxima", detail="el tamaño supera el máximo por mercado")
        exposure_cap = facts.equity_usd * config.risk.max_exposure_pct
        open_notional = book.position.notional_usd if book.position else Decimal("0")
        if open_notional + proposal.notional_usd > exposure_cap:
            return Veto(rule="exposicion_total", detail="la exposición total superaría el máximo")
        fee, slip, gas = total_cost_usd(
            proposal.notional_usd,
            facts.fee_schedule,
            facts.spread_bps,
            facts.liquidity_usd,
            facts.extra_bps,
        )
        edge = proposal.notional_usd * facts.expected_edge_bps / Decimal("10000")
        if edge <= fee + slip + gas:
            return Veto(rule="economia", detail="la ventaja no cubre comisión, slippage y gas")

    if proposal.bot == "house" and facts.price is not None:
        if facts.range_low is not None and facts.price < facts.range_low:
            return Veto(rule="rango", detail="precio bajo el rango", close_position=book.position is not None)
        if facts.range_high is not None and facts.price > facts.range_high:
            return Veto(rule="rango", detail="precio sobre el rango", close_position=book.position is not None)

    if book.position is not None and facts.volume_ratio is not None and facts.volume_ratio < Decimal("0.20"):
        return Veto(rule="salida_volumen", detail="volumen de 6 h bajo el ritmo", close_position=True)
    return None


def contract_veto(flags: dict) -> Veto | None:
    """Banderas duras de Spy. Se evalúan en código, antes de preguntar al modelo."""
    if flags.get("honeypot") is True:
        return Veto(rule="contrato", detail="honeypot")
    if flags.get("mint_authority_open") is True:
        return Veto(rule="contrato", detail="mint authority abierta")
    if flags.get("liquidity_locked") is False:
        return Veto(rule="contrato", detail="liquidez sin bloquear")
    return None
