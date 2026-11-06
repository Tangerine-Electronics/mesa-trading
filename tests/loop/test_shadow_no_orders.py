from datetime import timedelta

from mesa_trading.loop.cycle import run_cycle
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def test_a22_shadow_day_creates_no_orders(tmp_path):
    env = make_env(tmp_path, ScriptedJudge(bullish()), connector_for(T0, future_open="70100"), mode="shadow", markets=["BTC-PERP"])
    for index in range(288):
        moment = T0 + timedelta(minutes=5 * index)
        run_cycle(env, f"s{index}", moment)
    assert env.submits == []
    kinds = {event["event_type"] for event in env.logs.all_events()}
    assert "OrderSubmitted" not in kinds
    assert "CycleFinished" in kinds
    assert "PolicyDecided" in kinds
