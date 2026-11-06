from datetime import datetime, timezone
from decimal import Decimal

from mesa_trading.filter.funnel import cheap, hard, silent_step_alerts
from mesa_trading.loop.cycle import run_cycle
from mesa_trading.reports.build import build_daily
from mesa_trading.config import load_desk, repo_root
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def test_a19_rejection_records_step_and_silent_filter_alerts(tmp_path):
    connector = connector_for(T0)
    connector._books["BTC-PERP"]["bid"] = "50"
    connector._books["BTC-PERP"]["ask"] = "150"
    env = make_env(tmp_path, ScriptedJudge(bullish()), connector, mode="shadow", markets=["BTC-PERP"])
    run_cycle(env, "ancho", T0)
    rejected = [event for event in env.logs.all_events() if event["event_type"] == "CandidateRejected"]
    assert rejected
    assert rejected[0]["payload"]["step"]
    assert rejected[0]["payload"]["reason"]
    snapshot = {"age_s": 1, "spread_bps": "1", "liquidity_usd": "100000"}
    assert hard(snapshot).reason is None
    assert hard({**snapshot, "age_s": None}).reason == "datos_viejos"
    assert cheap(snapshot, notional_usd=Decimal("20"), min_fee_usd=Decimal("0.95")).reason == "economia"
    events = [
        {
            "event_type": "CycleFinished",
            "occurred_at": "2026-11-06T18:00:00.000000Z",
            "bot": "",
            "mode": "shadow",
            "payload": {"funnel_reached": {"hechos_duros": 50}, "funnel_rejected": {}},
            "correlation_id": "x",
            "event_id": "e",
        }
    ]
    report = build_daily(events, load_desk(repo_root() / "config" / "desk.yaml"), datetime(2026, 11, 6, 19, tzinfo=timezone.utc))
    assert "filtro_mudo:hechos_duros" in report["alertas"]
    assert silent_step_alerts({"hechos_duros": 50}, {}) == ["filtro_mudo:hechos_duros"]
