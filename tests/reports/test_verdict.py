from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mesa_trading.config import load_desk, load_promotion, repo_root
from mesa_trading.reports.build import PAIR_ID_CAP, apply_verdict, build_calibration, build_daily, update_pair_store

NOW = datetime(2026, 11, 20, 18, tzinfo=timezone.utc)


def _daily():
    events = [
        {
            "event_type": "CycleFinished",
            "occurred_at": "2026-11-20T17:00:00.000000Z",
            "bot": "",
            "mode": "",
            "payload": {
                "funnel": {"vistos": 6, "en_banca": 1, "alcanzados": {"hechos_duros": 5}},
                "funnel_reached": {"hechos_duros": 5},
            },
            "event_id": "f",
            "correlation_id": "c",
        }
    ]
    return build_daily(events, load_desk(repo_root() / "config" / "desk.yaml"), NOW, book={"realized_pnl_usd": "12.5", "drawdown_usd": "1"})


def test_verdict_waits_for_sample_and_estimates_days():
    promo = load_promotion(repo_root() / "config" / "promotion.yaml")
    calibration = build_calibration([], promo, load_desk(repo_root() / "config" / "desk.yaml"), NOW)
    started = (NOW - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    report = apply_verdict(
        _daily(),
        calibration,
        promo,
        closed_trades=40,
        started_at=started,
        capital_usd=Decimal("1000"),
        max_drawdown_usd=Decimal("1"),
        now=NOW,
    )
    verdict = report["veredicto"]
    assert verdict["estado"] == "insuficiente"
    assert verdict["operaciones_cerradas"] == 40
    assert verdict["min_operaciones"] == 200
    assert verdict["cierres_por_dia"] == 10
    assert verdict["dias_estimados_para_muestra"] == 16
    assert "no autoriza dinero real" in verdict["nota"]
    assert report["embudo"]["candidatos_vistos"] == 6
    assert report["embudo"]["en_banca"] == 1


def test_verdict_no_go_on_drawdown_and_go_when_sample_is_good():
    promo = load_promotion(repo_root() / "config" / "promotion.yaml")
    config = load_desk(repo_root() / "config" / "desk.yaml")
    events = []
    for index in range(30):
        events.append(
            {
                "event_id": f"b{index}",
                "event_type": "BatteryAnswered",
                "occurred_at": "2026-11-20T17:00:00.000000Z",
                "bot": "gambler",
                "mode": "simulated",
                "payload": {"answers": [{"question_id": "presion_compra", "probs": {"si": 0.8, "no": 0.2}}]},
            }
        )
        events.append(
            {
                "event_id": f"o{index}",
                "event_type": "OutcomeResolved",
                "occurred_at": "2026-11-20T17:30:00.000000Z",
                "bot": "gambler",
                "mode": "simulated",
                "payload": {"question_id": "presion_compra", "outcome": "si", "source_event": f"b{index}"},
            }
        )
    store = update_pair_store(None, events)
    again = update_pair_store(store, events)
    assert len(again["pares"]["gambler"]["presion_compra"]) == 30
    calibration = build_calibration(events, promo, config, NOW, pair_store=store)
    started = (NOW - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    blocked = apply_verdict(
        _daily(),
        calibration,
        promo,
        closed_trades=200,
        started_at=started,
        capital_usd=Decimal("1000"),
        max_drawdown_usd=Decimal("200"),
        now=NOW,
    )
    assert blocked["veredicto"]["estado"] == "no_go"
    # presion_compra no es pregunta de política; sin skill de política el go no sale.
    # Forzamos skill alto en una pregunta de política para el caso go.
    calibration["preguntas"]["gambler"]["regimen"]["skill"] = 0.05
    calibration["preguntas"]["gambler"]["setup"]["skill"] = 0.05
    calibration["preguntas"]["gambler"]["accion"]["skill"] = 0.05
    calibration["preguntas"]["gambler"]["ejecucion_degradada"]["skill"] = 0.05
    opened = apply_verdict(
        _daily(),
        calibration,
        promo,
        closed_trades=200,
        started_at=started,
        capital_usd=Decimal("1000"),
        max_drawdown_usd=Decimal("10"),
        now=NOW,
    )
    assert opened["veredicto"]["estado"] == "go_tentativo"


def test_pair_ids_are_capped():
    store = {"ids": [f"old-{index}" for index in range(PAIR_ID_CAP)], "pares": {}}
    events = [
        {
            "event_id": "nuevo",
            "event_type": "BatteryAnswered",
            "occurred_at": "2026-11-20T17:00:00.000000Z",
            "bot": "gambler",
            "mode": "simulated",
            "payload": {"answers": [{"question_id": "presion_compra", "probs": {"si": 0.8, "no": 0.2}}]},
        },
        {
            "event_id": "out",
            "event_type": "OutcomeResolved",
            "occurred_at": "2026-11-20T17:30:00.000000Z",
            "bot": "gambler",
            "mode": "simulated",
            "payload": {"question_id": "presion_compra", "outcome": "si", "source_event": "nuevo"},
        },
    ]
    merged = update_pair_store(store, events)
    assert len(merged["ids"]) == PAIR_ID_CAP
    assert "nuevo:presion_compra" in merged["ids"]
    assert "old-0" not in merged["ids"]


def test_flat_pnl_after_the_sample_is_no_go():
    promo = load_promotion(repo_root() / "config" / "promotion.yaml")
    config = load_desk(repo_root() / "config" / "desk.yaml")
    calibration = build_calibration([], promo, config, NOW)
    for qid in ("regimen", "setup", "accion", "ejecucion_degradada"):
        calibration["preguntas"]["gambler"][qid]["skill"] = 0.0
    started = (NOW - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    daily = _daily()
    daily["pnl_acumulado_usd"] = "0"
    report = apply_verdict(
        daily,
        calibration,
        promo,
        closed_trades=220,
        started_at=started,
        capital_usd=Decimal("1000"),
        max_drawdown_usd=Decimal("0"),
        now=NOW,
    )
    assert report["veredicto"]["estado"] == "no_go"
