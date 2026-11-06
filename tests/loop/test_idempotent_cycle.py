from mesa_trading.loop.cycle import run_cycle
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def test_a18_repeat_cycle_does_not_duplicate(tmp_path):
    env = make_env(
        tmp_path,
        ScriptedJudge(bullish()),
        connector_for(T0, future_open="70100"),
        mode="simulated",
        markets=["BTC-PERP"],
    )
    first = run_cycle(env, "mismo", T0)
    events = len(env.logs.all_events())
    orders = len(env.submits)
    second = run_cycle(env, "mismo", T0)
    assert second["idempotent"] is True
    assert len(env.logs.all_events()) == events
    assert len(env.submits) == orders
    assert orders == first["orders"]
    assert orders == 1
