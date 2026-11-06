from decimal import Decimal

from mesa_trading.policy.decide import apply_calibration, decide, platt


def _answers():
    return {
        "regimen": {"probs": {"tendencia": "0.9", "reversion": "0.04", "caotico": "0.03", "otro": "0.03"}},
        "setup": {"score": "2.5", "probs": {"0": "0", "1": "0", "2": "0.5", "3": "0.5"}},
        "accion": {"probs": {"largo": "0.8", "corto": "0.1", "hold": "0.1"}},
        "ejecucion_degradada": {"probs": {"si": "0.1", "no": "0.9"}},
        "estado_rango": {"probs": {"dentro": "0.8", "borde": "0.1", "rompiendo": "0.05", "otro": "0.05"}},
        "flujo_toxico": {"probs": {"si": "0.1", "no": "0.9"}},
        "vale_cotizar": {"score": "2.4", "probs": {"0": "0", "1": "0", "2": "0.6", "3": "0.4"}},
        "hay_volumen": {"probs": {"si": "0.9", "no": "0.1"}},
    }


def test_policy_paths():
    answers = _answers()
    long = decide("gambler", "BTC-PERP", "perp", answers, capital_usd=Decimal("1000"), mode="shadow")
    assert long.action == "long" and long.notional_usd == Decimal("250.00")
    spot_short = dict(answers)
    spot_short["accion"] = {"probs": {"largo": "0.1", "corto": "0.8", "hold": "0.1"}}
    held = decide("gambler", "BTC-USD", "spot", spot_short, capital_usd=Decimal("1000"), mode="shadow")
    assert held.reason == "corto_en_spot"
    weak = dict(answers)
    weak["regimen"] = {"probs": {"tendencia": "0.1", "reversion": "0.7", "caotico": "0.1", "otro": "0.1"}}
    assert decide("gambler", "BTC-PERP", "perp", weak, capital_usd=Decimal("1000"), mode="shadow").action == "hold"
    house = decide("house", "BTC-USD", "spot", answers, capital_usd=Decimal("1000"), mode="shadow")
    assert house.action == "quote"
    toxic = dict(answers)
    toxic["flujo_toxico"] = {"probs": {"si": "0.9", "no": "0.1"}}
    assert decide("house", "BTC-USD", "spot", toxic, capital_usd=Decimal("1000"), mode="shadow").action == "pause"
    breaking = dict(answers)
    breaking["estado_rango"] = {"probs": {"dentro": "0.1", "borde": "0.1", "rompiendo": "0.7", "otro": "0.1"}}
    assert decide("house", "BTC-USD", "spot", breaking, capital_usd=Decimal("1000"), mode="shadow", managing=True).action == "close"
    assert decide("gambler", "BTC-PERP", "perp", answers, capital_usd=Decimal("1000"), mode="simulated") .action == "hold"
    assert platt(Decimal("0.5"), Decimal("1"), Decimal("0")) == Decimal("0.5")
    assert apply_calibration({"si": Decimal("0.5"), "no": Decimal("0.5")}, curve=None, mode="shadow")["si"] == Decimal("0.5")
    assert apply_calibration({"si": Decimal("0.5")}, curve=None, mode="simulated") is None
    curved = apply_calibration({"si": Decimal("0.7"), "no": Decimal("0.3")}, curve={"a": "1", "b": "0"}, mode="simulated")
    assert curved is not None and abs(curved["si"] - Decimal("0.7")) < Decimal("0.01")
    assert decide("spy", "X", "spot", {}, capital_usd=Decimal("1000"), mode="shadow").reason == "bot_sin_politica_activa"
    assert decide("gambler", "BTC-PERP", "perp", {"regimen": answers["regimen"]}, capital_usd=Decimal("1000"), mode="shadow").reason == "respuesta_incompleta"
    unknown = dict(answers)
    unknown["setup"] = {**answers["setup"], "unknown": True}
    assert decide("gambler", "BTC-PERP", "perp", unknown, capital_usd=Decimal("1000"), mode="shadow").reason == "dato_faltante"
    no_score = dict(answers)
    no_score["setup"] = {"probs": {"2": "0.4", "3": "0.6"}}
    assert decide("gambler", "BTC-PERP", "perp", no_score, capital_usd=Decimal("1000"), mode="shadow").action == "long"
    missing_option = dict(answers)
    missing_option["ejecucion_degradada"] = {"probs": {"no": "1"}}
    assert decide("gambler", "BTC-PERP", "perp", missing_option, capital_usd=Decimal("1000"), mode="shadow").reason == "dato_faltante"
    assert decide("house", "BTC-USD", "spot", {"estado_rango": answers["estado_rango"]}, capital_usd=Decimal("1000"), mode="shadow").reason == "respuesta_incompleta"
    quiet = dict(answers)
    quiet["hay_volumen"] = {"probs": {"si": "0.1", "no": "0.9"}}
    assert decide("house", "BTC-USD", "spot", quiet, capital_usd=Decimal("1000"), mode="shadow").reason == "sin_volumen"
    assert decide("house", "BTC-USD", "spot", answers, capital_usd=Decimal("1000"), mode="shadow", managing=True).reason == "mantener_grid"
    no_prob = dict(answers)
    no_prob["hay_volumen"] = {"probs": {}}
    assert decide("house", "BTC-USD", "spot", no_prob, capital_usd=Decimal("1000"), mode="shadow").reason == "dato_faltante"
