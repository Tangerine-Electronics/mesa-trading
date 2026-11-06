from datetime import timedelta
from decimal import Decimal

from mesa_trading.broker.fees import FeeSchedule
from mesa_trading.broker.sim import SimBroker
from mesa_trading.models import Order
from mesa_trading.state.snapshot import build_snapshot
from tests.helpers import T0


def _candles():
    past = []
    price = Decimal("100")
    start = T0 - timedelta(hours=2)
    for index in range(20):
        ts = start + timedelta(minutes=5 * index)
        past.append(
            {
                "ts": ts,
                "close_ts": ts + timedelta(minutes=5),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": Decimal("5"),
            }
        )
    future_ts = T0 + timedelta(minutes=5)
    future = {
        "ts": future_ts,
        "close_ts": future_ts + timedelta(minutes=5),
        "open": Decimal("80"),
        "high": Decimal("81"),
        "low": Decimal("79"),
        "close": Decimal("80"),
        "volume": Decimal("5"),
    }
    return past, future


def test_a14_snapshot_ignores_the_future_and_broker_uses_next_candle():
    past, future = _candles()
    raw = {"candles": past + [future], "order_book": None, "funding": None}
    snapshot = build_snapshot("gambler", "BTC-USD", raw, T0)
    assert snapshot["last_close"] == "100.000000"
    broker = SimBroker(
        candles={"BTC-USD": past + [future]},
        fee_schedule=FeeSchedule(taker_bps=Decimal("0"), min_fee_usd=Decimal("0"), gas_usd=Decimal("0")),
        spread_bps=Decimal("0"),
        liquidity_usd=Decimal("100000000"),
        extra_bps=Decimal("0"),
    )
    order = Order(
        client_order_id="abc",
        cycle_id="c",
        bot="gambler",
        market="BTC-USD",
        side="buy",
        action="long",
        order_type="market",
        qty=Decimal("1"),
        notional_usd=Decimal("80"),
        decision_time=T0,
    )
    ack = broker.submit(order)
    assert ack.accepted
    fills = broker.fills()
    assert len(fills) == 1
    assert fills[0].price_source == "siguiente_vela"
    assert abs(fills[0].price - Decimal("80")) < Decimal("0.01")
    assert fills[0].price != Decimal("100")
    again = broker.submit(order)
    assert again.detail == "idempotente"
    assert len(broker.fills()) == 1
