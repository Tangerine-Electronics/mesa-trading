from datetime import timedelta
from decimal import Decimal

import pytest

from mesa_trading.broker.factory import ShadowGate, make_broker
from mesa_trading.broker.fees import FeeSchedule, slippage_usd
from mesa_trading.broker.sim import SimBroker
from mesa_trading.models import Order
from tests.helpers import T0


def _order(**kwargs) -> Order:
    base = dict(
        client_order_id="1",
        cycle_id="c",
        bot="house",
        market="BTC-USD",
        side="buy",
        action="quote",
        order_type="limit",
        qty=Decimal("1"),
        notional_usd=Decimal("100"),
        limit_price=Decimal("90"),
        decision_time=T0,
    )
    base.update(kwargs)
    return Order(**base)


def test_limit_cross_cancel_and_shadow():
    future = T0 + timedelta(minutes=5)
    candles = {
        "BTC-USD": [
            {
                "ts": future,
                "open": Decimal("100"),
                "high": Decimal("110"),
                "low": Decimal("80"),
                "close": Decimal("100"),
                "tick": Decimal("0.01"),
            }
        ]
    }
    broker = SimBroker(
        candles=candles,
        fee_schedule=FeeSchedule(taker_bps=Decimal("0"), min_fee_usd=Decimal("0.95"), gas_usd=Decimal("0.05")),
        spread_bps=Decimal("0"),
        liquidity_usd=Decimal("100000000"),
        extra_bps=Decimal("0"),
        last_prices={"BTC-USD": Decimal("100")},
    )
    assert broker.submit(_order()).accepted
    assert broker.fills()[0].fee_usd == Decimal("0.95")
    assert broker.positions()
    broker.cancel("2")
    missed = broker.submit(_order(client_order_id="2", limit_price=Decimal("200"), side="buy"))
    assert missed.accepted is False
    close = broker.submit(
        _order(client_order_id="3", order_type="market", action="close", side="sell", reason="cierre_sin_datos", market="BTC-USD")
    )
    assert close.accepted
    assert broker.balance() != Decimal("1000")
    no_future = SimBroker(candles={"BTC-USD": []}, last_prices={})
    assert no_future.submit(_order(client_order_id="4", order_type="market", action="long")).detail == "ack_sin_fill"
    assert no_future.submit(_order(client_order_id="5", reason="cierre_sin_datos", order_type="market")).detail == "ack_sin_fill"
    assert no_future.submit(_order(client_order_id="6", limit_price=None)).detail == "ack_sin_fill"
    has_candle = SimBroker(candles=candles)
    assert has_candle.submit(_order(client_order_id="8", limit_price=None, order_type="limit")).detail == "ack_sin_fill"
    sell = broker.submit(
        _order(client_order_id="7", side="sell", action="quote", limit_price=Decimal("90"), order_type="limit")
    )
    assert sell.accepted
    assert broker.fills(T0)
    assert slippage_usd(Decimal("10"), Decimal("1"), Decimal("0"), Decimal("1")) > 0
    gate = make_broker("shadow")
    assert isinstance(gate, ShadowGate)
    gate.note({"a": 1})
    with pytest.raises(RuntimeError):
        gate.submit(None)
