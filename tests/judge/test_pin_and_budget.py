from decimal import Decimal
from pathlib import Path

import pytest

from mesa_trading.config import DeskConfig, load_yaml, repo_root
from mesa_trading.constants import MONTHLY_BUDGET_USD, PINNED_MODEL
from mesa_trading.judge.runtime import BudgetBook, JudgeRuntime, StaticKey
from mesa_trading.loop.cycle import run_cycle
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def test_a7_latest_does_not_boot():
    raw = load_yaml(repo_root() / "config" / "desk.yaml")
    raw["judge"]["model"] = "jev-latest"
    with pytest.raises(ValueError):
        DeskConfig.model_validate(raw)
    raw["judge"]["model"] = "jev-1"
    with pytest.raises(ValueError):
        DeskConfig.model_validate(raw)


def test_a7_wrong_version_holds(tmp_path):
    judge = ScriptedJudge(bullish(model="jev-0.0.1"))
    env = make_env(tmp_path, judge, connector_for(T0), mode="simulated", markets=["BTC-PERP"])
    run_cycle(env, "c-version", T0)
    events = env.logs.all_events()
    assert any(event["event_type"] == "RiskVetoed" and event["payload"]["regla"] == "version_modelo" for event in events)
    assert env.submits == []
    answered = [event for event in events if event["event_type"] == "BatteryAnswered"]
    assert answered
    assert all(event["payload"]["model_version"] == "jev-0.0.1" for event in answered)


def test_a7_pinned_version_constant():
    assert PINNED_MODEL == "jev-1.14.0"
    assert MONTHLY_BUDGET_USD == Decimal("5")


class Boom:
    def __init__(self):
        self.calls = 0

    def __call__(self, url, key, body, timeout):
        self.calls += 1
        return 200, {"model": PINNED_MODEL, "answers": {}, "usage": {"input_tokens": 10}}


def test_bad_judge_timeout_does_not_crash(monkeypatch):
    from mesa_trading.cli.tick import RemoteJudge

    monkeypatch.setenv("MESA_JUDGE_TIMEOUT_S", "no-es-numero")
    judge = RemoteJudge("https://judge.invalid")
    result = judge.ask("c", "gambler", {"bot": "gambler"})
    assert result["status"] == "error"
    assert result["reason"] == "judge_error"


def test_daily_budget_blocks_before_the_call(tmp_path: Path):
    from datetime import datetime, timezone

    from mesa_trading.judge.runtime import CDMX

    day = datetime.now(timezone.utc).astimezone(CDMX).strftime("%Y-%m-%d")
    budget = BudgetBook(tmp_path / "budget.json")
    budget.add("1999-01", 4_000_000, day)
    transport = Boom()
    runtime = JudgeRuntime(StaticKey("present"), budget, transport, deadline_ms=2000, daily_budget_usd=Decimal("0.15"))
    result = runtime.battery("c", "gambler", {"bot": "gambler"})
    assert result["status"] == "budget_exceeded"
    assert result["reason"] == "budget_exceeded"
    assert transport.calls == 0


def test_a12_budget_blocks_before_the_call(tmp_path: Path):
    budget = BudgetBook(tmp_path / "budget.json")
    budget.add("2026-11", 120_000_000)
    transport = Boom()
    runtime = JudgeRuntime(StaticKey("present"), budget, transport, deadline_ms=2000)
    result = runtime.battery("c", "gambler", {"bot": "gambler"})
    assert result["status"] == "budget_exceeded"
    assert transport.calls == 0
