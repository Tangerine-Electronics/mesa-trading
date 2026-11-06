from datetime import datetime, timezone
from decimal import Decimal

from mesa_trading.config import load_desk, repo_root
from mesa_trading.reports.build import build_daily, render_daily_md

NOW = datetime(2026, 11, 6, 18, 30, tzinfo=timezone.utc)


def test_a24_daily_summary_is_after_costs_and_in_cdmx():
    events = [
        {
            "event_type": "PolicyDecided",
            "occurred_at": "2026-11-06T17:55:00.000000Z",
            "bot": "gambler",
            "mode": "shadow",
            "payload": {"action": "long", "threshold_version": 1, "thresholds": {"position_size_pct": "0.25"}},
            "event_id": "p",
            "correlation_id": "c",
        },
        {
            "event_type": "RiskVetoed",
            "occurred_at": "2026-11-06T17:55:01.000000Z",
            "bot": "gambler",
            "mode": "shadow",
            "payload": {"regla": "economia"},
            "event_id": "v",
            "correlation_id": "c",
        },
        {
            "event_type": "CandidateRejected",
            "occurred_at": "2026-11-06T17:55:02.000000Z",
            "bot": "house",
            "mode": "shadow",
            "payload": {"step": "hechos_duros", "reason": "spread_ancho"},
            "event_id": "r",
            "correlation_id": "c",
        },
        {
            "event_type": "PositionClosed",
            "occurred_at": "2026-11-06T17:56:00.000000Z",
            "bot": "gambler",
            "mode": "simulated",
            "payload": {"pnl_usd": "-1.25"},
            "event_id": "pc",
            "correlation_id": "c",
        },
        {
            "event_type": "BatteryAnswered",
            "occurred_at": "2026-11-06T17:56:01.000000Z",
            "bot": "gambler",
            "mode": "shadow",
            "payload": {"input_tokens": 1000, "answers": []},
            "event_id": "b",
            "correlation_id": "c",
        },
        {
            "event_type": "CycleFinished",
            "occurred_at": "2026-11-06T17:56:02.000000Z",
            "bot": "",
            "mode": "",
            "payload": {"funnel_reached": {}, "funnel_rejected": {}},
            "event_id": "f",
            "correlation_id": "c",
        },
    ]
    report = build_daily(events, load_desk(repo_root() / "config" / "desk.yaml"), NOW, book={"realized_pnl_usd": "-1.25", "drawdown_usd": "1.25"})
    assert Decimal(report["pnl_dia_usd"]) == Decimal("-1.25")
    assert report["vetos_por_regla"]["economia"] == 1
    assert report["rechazos_por_paso"]["hechos_duros"] == 1
    assert report["gasto_jev_usd"] == 1000 * 0.042 / 1_000_000
    assert "America/Mexico_City" in report["hora_cdmx"]
    text = render_daily_md(report)
    assert "Ciudad de México" in text
    assert "después de comisiones y slippage" in text
