"""SimBroker: ejecuta contra precios públicos con comisión y slippage.

Si hay una vela que abre después de la decisión, la orden de mercado sale a esa
apertura (backtest, sin lookahead). En vivo esa vela no existe: el conector
solo trae velas hasta ahora. Entonces la orden de mercado cruza el libro leído
después del reloj de la decisión: compra al ask, vende al bid. El medio spread
ya está en ese precio; encima se suman impacto, bps extra y comisión. No se
deja pendiente al siguiente tick: cinco minutos después el precio ya no es el
que se cruzó.

No tiene red y no importa ningún cliente HTTP.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from mesa_trading.broker.base import Broker
from mesa_trading.broker.fees import FeeSchedule, commission_usd, slippage_usd
from mesa_trading.models import Ack, Fill, Order
from mesa_trading.util import as_utc


class SimBroker(Broker):
    def __init__(
        self,
        candles: dict[str, list[dict]] | None = None,
        fee_schedule: FeeSchedule | None = None,
        spread_bps: Decimal = Decimal("2"),
        liquidity_usd: Decimal = Decimal("1000000"),
        extra_bps: Decimal = Decimal("1"),
        cash_usd: Decimal = Decimal("1000"),
        last_prices: dict[str, Decimal] | None = None,
        bid: Decimal | None = None,
        ask: Decimal | None = None,
    ) -> None:
        self.candles = candles or {}
        self.fee_schedule = fee_schedule or FeeSchedule(
            taker_bps=Decimal("60"), min_fee_usd=Decimal("0"), gas_usd=Decimal("0")
        )
        self.spread_bps = spread_bps
        self.liquidity_usd = liquidity_usd
        self.extra_bps = extra_bps
        self.cash_usd = cash_usd
        self.last_prices = dict(last_prices or {})
        self.bid = bid
        self.ask = ask
        self._orders: dict[str, Order] = {}
        self._fills: list[Fill] = []
        self._positions: dict[str, dict] = {}
        self._cancelled: set[str] = set()

    def submit(self, order: Order) -> Ack:
        if order.client_order_id in self._orders:
            return Ack(client_order_id=order.client_order_id, accepted=True, detail="idempotente")
        self._orders[order.client_order_id] = order
        if order.client_order_id in self._cancelled:
            return Ack(client_order_id=order.client_order_id, accepted=False, detail="cancelada")
        fill = self._try_fill(order)
        if fill is None:
            return Ack(client_order_id=order.client_order_id, accepted=True, detail="ack_sin_fill")
        self._apply_fill(fill, order)
        return Ack(client_order_id=order.client_order_id, accepted=True, detail="filled")

    def cancel(self, client_order_id: str) -> None:
        self._cancelled.add(client_order_id)

    def fills(self, since: datetime | None = None) -> list[Fill]:
        if since is None:
            return list(self._fills)
        start = as_utc(since)
        return [fill for fill in self._fills if as_utc(fill.filled_at) >= start]

    def positions(self) -> list[dict]:
        return [dict(item) for item in self._positions.values()]

    def balance(self) -> Decimal:
        return self.cash_usd

    def _try_fill(self, order: Order) -> Fill | None:
        if order.reason == "cierre_sin_datos":
            price = self.last_prices.get(order.market)
            if price is None:
                return None
            return self._make_fill(order, price, as_utc(order.decision_time), "ultimo_conocido")
        series = self.candles.get(order.market, [])
        nxt = _next_candle(series, order.decision_time)
        if nxt is None:
            return self._fill_at_book(order)
        if order.order_type == "market":
            return self._make_fill(order, nxt["open"], nxt["ts"], "siguiente_vela")
        if order.limit_price is None:
            return None
        tick = Decimal(str(nxt.get("tick", "0.01")))
        if order.side == "buy" and nxt["low"] <= order.limit_price - tick:
            return self._make_fill(order, order.limit_price, nxt["ts"], "cruce_limite")
        if order.side == "sell" and nxt["high"] >= order.limit_price + tick:
            return self._make_fill(order, order.limit_price, nxt["ts"], "cruce_limite")
        return None

    def _fill_at_book(self, order: Order) -> Fill | None:
        """Cruce del libro cuando no hay vela posterior. Solo órdenes de mercado."""
        if order.order_type != "market":
            return None
        touch = self.ask if order.side == "buy" else self.bid
        if touch is None or touch <= 0:
            return None
        # El ask/bid ya incluye el medio spread. El slippage de arriba no lo repite.
        return self._make_fill(
            order,
            touch,
            as_utc(order.decision_time),
            "libro",
            include_half_spread=False,
        )

    def _make_fill(
        self,
        order: Order,
        raw_price: Decimal,
        when: datetime,
        source: str,
        *,
        include_half_spread: bool = True,
    ) -> Fill:
        fee = commission_usd(order.notional_usd, self.fee_schedule)
        spread = self.spread_bps if include_half_spread else Decimal("0")
        slip = slippage_usd(order.notional_usd, spread, self.liquidity_usd, self.extra_bps)
        slip_per_unit = (slip / order.qty) if order.qty > 0 else Decimal("0")
        price = raw_price + slip_per_unit if order.side == "buy" else raw_price - slip_per_unit
        return Fill(
            client_order_id=order.client_order_id,
            market=order.market,
            side=order.side,
            qty=order.qty,
            price=price,
            fee_usd=fee,
            slippage_usd=slip,
            gas_usd=self.fee_schedule.gas_usd,
            filled_at=when,
            price_source=source,
            reason=order.reason,
        )

    def _apply_fill(self, fill: Fill, order: Order) -> None:
        self._fills.append(fill)
        cost = fill.fee_usd + fill.slippage_usd + fill.gas_usd
        signed = fill.qty * fill.price
        if fill.side == "buy":
            self.cash_usd -= signed + cost
            self._positions[order.market] = {
                "market": order.market,
                "qty": fill.qty,
                "side": "long" if order.action != "short" else "short",
            }
        else:
            self.cash_usd += signed - cost
            self._positions.pop(order.market, None)


def _next_candle(series: list[dict], decision_time: datetime) -> dict | None:
    decision = as_utc(decision_time)
    future = [candle for candle in series if as_utc(candle["ts"]) > decision]
    if not future:
        return None
    future.sort(key=lambda candle: as_utc(candle["ts"]))
    return future[0]
