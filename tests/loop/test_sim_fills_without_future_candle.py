"""El ciclo en vivo no tiene vela con ts posterior. Igual abre la posición."""

from decimal import Decimal

from mesa_trading.loop.cycle import run_cycle
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def test_simulated_cycle_fills_at_the_book(tmp_path):
    connector = connector_for(T0)
    judge = ScriptedJudge(bullish())
    env = make_env(tmp_path, judge, connector, mode="simulated", markets=["BTC-PERP"])
    run_cycle(env, "20261106T120000Z", T0)
    fills = [event for event in env.logs.all_events() if event["event_type"] == "OrderFilled"]
    assert len(fills) == 1
    assert fills[0]["payload"]["price_source"] == "libro"
    state, _gen = env.book.read()
    assert state.position is not None
    assert state.position.entry_price > Decimal("0")
    assert state.closed_trades == 0
