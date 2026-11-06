import pytest

from mesa_trading.cli.tick import main
from mesa_trading.config import repo_root
from mesa_trading.loop.cycle import run_cycle
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def test_a30_disabled_spy_does_not_build_or_call(tmp_path):
    wallets = {"n": 0}
    flags = {"n": 0}

    def wallet_factory():
        wallets["n"] += 1
        return object()

    def flags_factory():
        flags["n"] += 1
        return object()

    judge = ScriptedJudge(bullish())
    env = make_env(tmp_path, judge, connector_for(T0), mode="shadow", markets=["BTC-PERP"])
    env.wallet_factory = wallet_factory
    env.flags_factory = flags_factory
    assert env.config.bots["spy"].enabled is False
    run_cycle(env, "spy-off", T0)
    assert wallets["n"] == 0
    assert flags["n"] == 0
    assert "spy" not in judge.calls
    kinds = {event["event_type"] for event in env.logs.all_events() if event.get("bot") == "spy"}
    assert kinds == set()


def test_a30_enabled_without_sources_does_not_start(tmp_path):
    source = (repo_root() / "config" / "desk.yaml").read_text(encoding="utf-8")
    path = tmp_path / "desk.yaml"
    path.write_text(source.replace("spy:\n    enabled: false", "spy:\n    enabled: true"), encoding="utf-8")
    code = main(["--config", str(path), "--data-dir", str(tmp_path / "data"), "--fixture"])
    assert code == 2
    env = make_env(tmp_path / "run", ScriptedJudge(bullish()), connector_for(T0))
    env.config.bots["spy"].enabled = True
    with pytest.raises(SystemExit):
        run_cycle(env, "spy-on", T0)
