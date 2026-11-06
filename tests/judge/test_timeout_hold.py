from mesa_trading.judge.runtime import BudgetBook, JudgeRuntime, StaticKey
from mesa_trading.loop.cycle import run_cycle
from tests.helpers import T0, connector_for, make_env


class Slow:
    def __init__(self):
        self.calls = 0

    def __call__(self, url, key, body, timeout):
        self.calls += 1
        raise TimeoutError


def test_a10_timeout_is_hold_without_orders(tmp_path):
    transport = Slow()
    runtime = JudgeRuntime(StaticKey("k"), BudgetBook(tmp_path / "b.json"), transport, deadline_ms=50)
    result = runtime.battery("c", "gambler", {"bot": "gambler"})
    assert result["status"] == "timeout"
    assert transport.calls == 1

    class TimeoutJudge:
        def __init__(self):
            self.calls = []

        def ask(self, cycle_id, bot, snapshot):
            self.calls.append(bot)
            return result

    judge = TimeoutJudge()
    env = make_env(tmp_path / "desk", judge, connector_for(T0), mode="simulated", markets=["BTC-PERP"])
    run_cycle(env, "c-timeout", T0)
    kinds = [event["event_type"] for event in env.logs.all_events()]
    assert "BatteryTimedOut" in kinds
    assert "OrderSubmitted" not in kinds
    assert env.submits == []
