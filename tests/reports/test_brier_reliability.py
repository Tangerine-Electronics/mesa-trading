import pytest

from mesa_trading.config import load_desk, load_promotion, repo_root
from mesa_trading.reports.build import brier_baseline, brier_binary, build_calibration, reliability, skill


def _event(kind, event_id, bot, payload, when="2026-11-06T18:00:00.000000Z"):
    return {
        "event_id": event_id,
        "event_type": kind,
        "occurred_at": when,
        "bot": bot,
        "mode": "shadow",
        "correlation_id": "c",
        "payload": payload,
    }


def test_a23_brier_matches_hand_calculation():
    pairs = [(0.2, 0), (0.8, 1), (0.8, 1), (0.2, 0)]
    assert brier_binary(pairs) == pytest.approx(0.04)
    assert brier_baseline(pairs) == pytest.approx(0.25)
    assert skill(0.04, 0.25) == pytest.approx(0.84)
    curve = reliability(pairs)
    assert len(curve) == 10
    bucket_20 = curve[2]
    assert bucket_20["n"] == 2
    assert bucket_20["frecuencia"] == 0
    events = []
    samples = [(0.2, "no"), (0.8, "si"), (0.8, "si"), (0.2, "no")]
    for index, (prob, outcome) in enumerate(samples):
        events.append(
            _event(
                "BatteryAnswered",
                f"b{index}",
                "gambler",
                {"answers": [{"question_id": "presion_compra", "probs": {"si": prob, "no": 1 - prob}}]},
            )
        )
        events.append(
            _event(
                "OutcomeResolved",
                f"o{index}",
                "gambler",
                {"question_id": "presion_compra", "outcome": outcome, "source_event": f"b{index}"},
            )
        )
    report = build_calibration(
        events,
        load_promotion(repo_root() / "config" / "promotion.yaml"),
        load_desk(repo_root() / "config" / "desk.yaml"),
        __import__("tests.helpers", fromlist=["T0"]).T0,
    )
    question = report["preguntas"]["gambler"]["presion_compra"]
    assert question["brier"] == pytest.approx(0.04)
    assert question["brier_base"] == pytest.approx(0.25)
    assert question["skill"] == pytest.approx(0.84)
