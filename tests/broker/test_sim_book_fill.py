"""Sin vela posterior, la orden de mercado cruza el libro. Con vela, no."""

from datetime import timedelta
from decimal import Decimal

from mesa_trading.broker.fees import FeeSchedule
from mesa_trading.broker.sim import SimBroker
from mesa_trading.models import Order
from tests.helpers import T0, series


def _order(side: str = "buy") -> Order:
    return Order(
        client_order_id="abc" if side == "buy" else "def",
        cycle_id="c",
        bot="gambler",
        market="BTC-PERP",
        side=side,
        action="long" if side == "buy" else "short",
        order_type="market",
        qty=Decimal("1"),
        notional_usd=Decimal("100"),
        decision_time=T0,
    )


def _broker(candles: list[dict], **kwargs) -> SimBroker:
    defaults = dict(
        fee_schedule=FeeSchedule(taker_bps=Decimal("10"), min_fee_usd=Decimal("0"), gas_usd=Decimal("0")),
        spread_bps=Decimal("20"),
        liquidity_usd=Decimal("100000000"),
        extra_bps=Decimal("0"),
        bid=Decimal("99.5"),
        ask=Decimal("100.5"),
    )
    defaults.update(kwargs)
    return SimBroker(candles={"BTC-PERP": candles}, **defaults)


def test_market_order_fills_the_book_when_no_candle_is_after_the_decision():
    # Todas las velas abren en o antes de T0. Antes esto devolvía ack_sin_fill.
    past = series(T0 - timedelta(minutes=20), n=4, price="100")
    assert all(candle["ts"] <= T0 for candle in past)
    broker = _broker(past)
    ack = broker.submit(_order("buy"))
    assert ack.accepted
    assert ack.detail == "filled"
    fill = broker.fills()[0]
    assert fill.price_source == "libro"
    # El ask ya trae el medio spread. El slippage que se suma es solo el impacto.
    assert fill.slippage_usd > 0
    assert fill.price == Decimal("100.5") + fill.slippage_usd
    assert fill.fee_usd == Decimal("0.1")
    sell = _broker(
        past,
        fee_schedule=FeeSchedule(taker_bps=Decimal("0"), min_fee_usd=Decimal("0"), gas_usd=Decimal("0")),
    )
    sell.submit(_order("sell"))
    sold = sell.fills()[0]
    assert sold.price_source == "libro"
    assert sold.price == Decimal("99.5") - sold.slippage_usd


def test_a_later_candle_still_wins_over_the_book():
    past = series(T0 - timedelta(minutes=20), n=4, price="100")
    future = {
        "ts": T0 + timedelta(minutes=5),
        "close_ts": T0 + timedelta(minutes=10),
        "open": Decimal("80"),
        "high": Decimal("81"),
        "low": Decimal("79"),
        "close": Decimal("80"),
        "volume": Decimal("5"),
    }
    broker = _broker(
        past + [future],
        fee_schedule=FeeSchedule(taker_bps=Decimal("0"), min_fee_usd=Decimal("0"), gas_usd=Decimal("0")),
        spread_bps=Decimal("0"),
    )
    broker.submit(_order("buy"))
    fill = broker.fills()[0]
    assert fill.price_source == "siguiente_vela"
    assert abs(fill.price - Decimal("80")) < Decimal("0.01")
