"""Umbrales en código. La probabilidad no cambia el tamaño de la posición."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from mesa_trading.config import default_policy_path
from mesa_trading.models import Proposal


def load_policy(path: Path | None = None) -> dict[str, Any]:
    target = path or default_policy_path()
    return yaml.safe_load(target.read_text(encoding="utf-8"))


def platt(probability: Decimal, a: Decimal, b: Decimal) -> Decimal:
    clipped = min(Decimal("0.999"), max(Decimal("0.001"), probability))
    logit = (clipped / (Decimal("1") - clipped)).ln()
    z = a * logit + b
    return Decimal("1") / (Decimal("1") + (-z).exp())


def apply_calibration(
    probs: dict[str, Decimal],
    *,
    curve: dict[str, str] | None,
    mode: str,
) -> dict[str, Decimal] | None:
    """Sin curva aprobada, la probabilidad cruda solo se usa en sombra."""
    if curve:
        a = Decimal(curve["a"])
        b = Decimal(curve["b"])
        adjusted = {key: platt(value, a, b) for key, value in probs.items()}
        total = sum(adjusted.values())
        return {key: value / total for key, value in adjusted.items()}
    if mode == "shadow":
        return dict(probs)
    return None


def decide(
    bot: str,
    market: str,
    kind: str,
    answers: dict[str, dict],
    *,
    capital_usd: Decimal,
    mode: str,
    policy: dict[str, Any] | None = None,
    curves: dict[str, dict] | None = None,
    managing: bool = False,
) -> Proposal:
    rules = (policy or load_policy())[bot]
    version = int((policy or load_policy()).get("version", 1))
    curves = curves or {}
    usable = _usable_answers(bot, answers, mode, curves)
    if usable is None:
        return _hold(bot, market, kind, version, rules, "sin_calibracion_aprobada")
    if bot == "gambler":
        return _gambler(market, kind, usable, capital_usd, rules, version, managing)
    if bot == "house":
        return _house(market, kind, usable, capital_usd, rules, version, managing)
    return _hold(bot, market, kind, version, rules, "bot_sin_politica_activa")


def _usable_answers(bot, answers, mode, curves):
    out = {}
    for qid, answer in answers.items():
        probs = {key: Decimal(str(value)) for key, value in (answer.get("probs") or {}).items()}
        calibrated = apply_calibration(probs, curve=curves.get(f"{bot}.{qid}"), mode=mode)
        if calibrated is None and mode != "shadow":
            return None
        out[qid] = {**answer, "probs": calibrated if calibrated is not None else probs}
    return out


def _p(answer: dict, option: str) -> Decimal | None:
    probs = answer.get("probs") or {}
    if option not in probs:
        return None
    return Decimal(str(probs[option]))


def _score(answer: dict) -> Decimal | None:
    if answer.get("score") is not None:
        return Decimal(str(answer["score"]))
    probs = answer.get("probs") or {}
    if not probs:
        return None
    total = Decimal("0")
    for key, value in probs.items():
        total += Decimal(str(key)) * Decimal(str(value))
    return total


def _size(capital: Decimal, pct: Decimal) -> Decimal:
    return (capital * pct).quantize(Decimal("0.01"))


def _hold(bot, market, kind, version, rules, reason) -> Proposal:
    return Proposal(
        bot=bot,
        market=market,
        action="hold",
        kind=kind,  # type: ignore[arg-type]
        threshold_version=version,
        thresholds=dict(rules),
        reason=reason,
        is_entry=False,
    )


def _gambler(market, kind, answers, capital, rules, version, managing) -> Proposal:
    needed = ("regimen", "setup", "accion", "ejecucion_degradada")
    if any(qid not in answers for qid in needed):
        return _hold("gambler", market, kind, version, rules, "respuesta_incompleta")
    if any(_missing_fields(answers[qid]) for qid in needed):
        return _hold("gambler", market, kind, version, rules, "dato_faltante")
    p_trend = _p(answers["regimen"], "tendencia")
    p_action = answers["accion"]["probs"]
    top = max(p_action, key=p_action.get)
    p_top = Decimal(str(p_action[top]))
    setup = _score(answers["setup"])
    p_bad = _p(answers["ejecucion_degradada"], "si")
    common = dict(bot="gambler", market=market, kind=kind, threshold_version=version, thresholds=dict(rules))
    if p_trend is None or setup is None or p_bad is None:
        return _hold("gambler", market, kind, version, rules, "dato_faltante")
    exit_now = (
        p_trend < Decimal(str(rules["regimen_tendencia_min_p"]))
        or top == "hold"
        or p_bad >= Decimal(str(rules["ejecucion_degradada_max_p"]))
    )
    if managing:
        action = "close" if exit_now else "hold"
        return Proposal(**common, action=action, reason="salida" if action == "close" else "mantener", is_entry=False)
    ok = (
        p_trend >= Decimal(str(rules["regimen_tendencia_min_p"]))
        and setup >= Decimal(str(rules["setup_min"]))
        and top != "hold"
        and p_top >= Decimal(str(rules["accion_min_p"]))
        and p_bad < Decimal(str(rules["ejecucion_degradada_max_p"]))
    )
    if not ok:
        return Proposal(**common, action="hold", reason="umbral", is_entry=False)
    if top == "corto" and kind == "spot":
        return Proposal(**common, action="hold", reason="corto_en_spot", is_entry=False)
    action = "short" if top == "corto" else "long"
    return Proposal(
        **common,
        action=action,
        notional_usd=_size(capital, Decimal(str(rules["position_size_pct"]))),
        reason="entrada",
        is_entry=True,
    )


def _house(market, kind, answers, capital, rules, version, managing) -> Proposal:
    needed = ("estado_rango", "flujo_toxico", "vale_cotizar", "hay_volumen")
    if any(qid not in answers for qid in needed):
        return _hold("house", market, kind, version, rules, "respuesta_incompleta")
    p_break = _p(answers["estado_rango"], "rompiendo")
    p_toxic = _p(answers["flujo_toxico"], "si")
    worth = _score(answers["vale_cotizar"])
    p_vol = _p(answers["hay_volumen"], "si")
    common = dict(bot="house", market=market, kind=kind, threshold_version=version, thresholds=dict(rules))
    if None in (p_break, p_toxic, worth, p_vol):
        return _hold("house", market, kind, version, rules, "dato_faltante")
    if p_break >= Decimal(str(rules["ruptura_min_p"])):
        return Proposal(**common, action="close" if managing else "pause", reason="ruptura", is_entry=False)
    if p_vol < Decimal(str(rules["volumen_min_p"])):
        return Proposal(**common, action="close" if managing else "pause", reason="sin_volumen", is_entry=False)
    if p_toxic >= Decimal(str(rules["toxico_max_p"])) or worth < Decimal(str(rules["vale_cotizar_min"])):
        return Proposal(**common, action="pause", reason="toxico_o_no_conviene", is_entry=False)
    if managing:
        return Proposal(**common, action="hold", reason="mantener_grid", is_entry=False)
    return Proposal(
        **common,
        action="quote",
        notional_usd=_size(capital, Decimal(str(rules["position_size_pct"]))),
        reason="cotizar",
        is_entry=True,
    )


def _missing_fields(answer: dict) -> bool:
    return bool(answer.get("unknown"))
