"""Calibración, Brier y resumen diario. El reporte recomienda; no cambia el modo."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from mesa_trading.config import DeskConfig, PromotionConfig
from mesa_trading.questions.catalog import battery_for
from mesa_trading.filter.funnel import silent_step_alerts
from mesa_trading.util import as_utc, iso

CDMX = ZoneInfo("America/Mexico_City")
POLICY_QUESTIONS = {
    "gambler": ("regimen", "setup", "accion", "ejecucion_degradada"),
    "house": ("estado_rango", "flujo_toxico", "vale_cotizar", "hay_volumen"),
    "spy": ("perfil", "consistente", "copiar", "rug"),
}


def brier_binary(pairs: list[tuple[float, int]]) -> float | None:
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def brier_baseline(pairs: list[tuple[float, int]]) -> float | None:
    if not pairs:
        return None
    rate = sum(y for _, y in pairs) / len(pairs)
    return sum((rate - y) ** 2 for _, y in pairs) / len(pairs)


def skill(score: float | None, base: float | None) -> float | None:
    if score is None or base is None or base == 0:
        return None
    return 1 - score / base


def reliability(pairs: list[tuple[float, int]]) -> list[dict]:
    buckets: list[dict] = []
    for index in range(10):
        low = index / 10
        high = (index + 1) / 10
        chosen = [item for item in pairs if (low <= item[0] < high) or (index == 9 and item[0] == 1)]
        if not chosen:
            buckets.append({"desde": low, "hasta": high, "n": 0, "probabilidad_media": None, "frecuencia": None, "desvio_pp": None})
            continue
        mean_p = sum(p for p, _ in chosen) / len(chosen)
        freq = sum(y for _, y in chosen) / len(chosen)
        buckets.append(
            {
                "desde": low,
                "hasta": high,
                "n": len(chosen),
                "probabilidad_media": mean_p,
                "frecuencia": freq,
                "desvio_pp": abs(freq - mean_p) * 100,
            }
        )
    return buckets


def propose_platt(pairs: list[tuple[float, int]]) -> dict | None:
    if len(pairs) < 10 or len({y for _, y in pairs}) < 2:
        return None
    mean_p = sum(p for p, _ in pairs) / len(pairs)
    rate = sum(y for _, y in pairs) / len(pairs)
    return {"a": 1.0, "b": _logit(rate) - _logit(mean_p), "nota": "propuesta, no aplicada"}


def forecast_pairs(events: list[dict], question_id: str) -> list[tuple[float, int]]:
    outcomes = {}
    for event in events:
        if event["event_type"] != "OutcomeResolved":
            continue
        payload = event["payload"]
        if payload.get("question_id") != question_id:
            continue
        outcomes[payload["source_event"]] = payload["outcome"]
    pairs = []
    for event in events:
        if event["event_type"] != "BatteryAnswered":
            continue
        if event["event_id"] not in outcomes:
            continue
        answer = _answer(event, question_id)
        if answer is None:
            continue
        probs = answer.get("probs") or {}
        outcome = outcomes[event["event_id"]]
        if "si" in probs and outcome in {"si", "no"}:
            pairs.append((float(probs["si"]), 1 if outcome == "si" else 0))
            continue
        if not probs:
            continue
        chosen = max(probs, key=probs.get)
        pairs.append((float(probs[chosen]), 1 if chosen == outcome else 0))
    return pairs


def readiness(bot: str, stats: dict, promo: PromotionConfig) -> dict:
    checks = [
        _check("min_shadow_days", stats["shadow_days"] >= promo.min_shadow_days, f"{stats['shadow_days']} días en sombra"),
        _check(
            "min_resolved_per_question",
            stats["min_resolved"] >= promo.min_resolved_per_question,
            f"mínimo resuelto {stats['min_resolved']}",
        ),
        _check(
            "min_brier_skill",
            stats["min_skill"] is not None and stats["min_skill"] >= float(promo.min_brier_skill),
            f"skill {stats['min_skill']}",
        ),
        _check(
            "min_bucket_samples",
            stats["buckets_ok"],
            "cubetas con muestra suficiente evaluadas" if stats["buckets_ok"] else "faltan cubetas con muestra",
        ),
        _check(
            "max_bucket_deviation_pp",
            stats["max_deviation_pp"] is None or stats["max_deviation_pp"] <= float(promo.max_bucket_deviation_pp),
            f"desvío {stats['max_deviation_pp']}",
        ),
        _check(
            "max_missed_cycle_pct",
            stats["missed_pct"] <= float(promo.max_missed_cycle_pct),
            f"ciclos perdidos {stats['missed_pct']}%",
        ),
    ]
    ready = all(item["ok"] for item in checks)
    return {"bot": bot, "listo_para_simulado": "sí" if ready else "no", "motivos": checks}


def build_calibration(events: list[dict], promo: PromotionConfig, config: DeskConfig, now: datetime) -> dict:
    per_bot = {}
    questions = {}
    for bot, policy_qids in POLICY_QUESTIONS.items():
        qids = tuple(question.id for question in battery_for(bot))
        bot_questions = {}
        skills = []
        deviations = []
        buckets_ok = True
        min_resolved = 10**9
        for qid in qids:
            pairs = [item for item in forecast_pairs(events, qid) if _event_bot(events, qid) in {bot, ""}]
            pairs = _pairs_for_bot(events, bot, qid)
            score = brier_binary(pairs)
            base = brier_baseline(pairs)
            sk = skill(score, base)
            curve = reliability(pairs)
            counted = [bucket for bucket in curve if bucket["n"] >= promo.min_bucket_samples]
            if qid in policy_qids:
                if not counted:
                    buckets_ok = False
                max_dev = max((bucket["desvio_pp"] for bucket in counted), default=None)
                if max_dev is not None:
                    deviations.append(max_dev)
                if sk is not None:
                    skills.append(sk)
                min_resolved = min(min_resolved, len(pairs))
            bot_questions[qid] = {
                "n": len(pairs),
                "brier": score,
                "brier_base": base,
                "skill": sk,
                "confiabilidad": curve,
                "platt": propose_platt(pairs),
            }
        if min_resolved == 10**9:
            min_resolved = 0
        missed = _missed_pct(events, config, now)
        stats = {
            "shadow_days": _shadow_days(events, bot, now),
            "min_resolved": min_resolved,
            "min_skill": min(skills) if skills else None,
            "buckets_ok": buckets_ok and min_resolved > 0,
            "max_deviation_pp": max(deviations) if deviations else None,
            "missed_pct": missed,
        }
        per_bot[bot] = readiness(bot, stats, promo)
        questions[bot] = bot_questions
    return {
        "fecha": _cdmx_date(now),
        "generado_en": iso(now),
        "zona": "America/Mexico_City",
        "modelo": config.judge.model,
        "preguntas": questions,
        "bots": per_bot,
        "agregados": _aggregates(questions),
    }


def build_daily(events: list[dict], config: DeskConfig, now: datetime, book: dict | None = None) -> dict:
    start, end = _window(now)
    window = [event for event in events if start <= _when(event) <= end]
    decisions: dict[str, int] = defaultdict(int)
    vetoes: dict[str, int] = defaultdict(int)
    rejected: dict[str, int] = defaultdict(int)
    reached: dict[str, int] = defaultdict(int)
    fills = []
    tokens = 0
    finished = 0
    halted = []
    for event in window:
        kind = event["event_type"]
        payload = event.get("payload") or {}
        if kind == "PolicyDecided":
            decisions[event.get("bot") or "?"] += 1
        elif kind == "RiskVetoed":
            vetoes[payload.get("regla") or "?"] += 1
        elif kind == "CandidateRejected":
            rejected[payload.get("step") or "?"] += 1
        elif kind == "CycleFinished":
            finished += 1
            for step, count in (payload.get("funnel_reached") or {}).items():
                reached[step] += int(count)
            for step, count in (payload.get("funnel_rejected") or {}).items():
                rejected[step] += 0
        elif kind == "OrderFilled":
            fills.append(payload)
        elif kind == "BatteryAnswered":
            tokens += int(payload.get("input_tokens") or 0)
        elif kind == "DeskHalted":
            halted.append(payload)
    expected = max(int((end - start).total_seconds() // (config.cadence_minutes * 60)), 1)
    missed = max(expected - finished, 0)
    pnl_day = _sum_pnl(window)
    alerts = []
    alerts.extend(silent_step_alerts(dict(reached), dict(rejected)))
    if halted:
        alerts.append("DeskHalted")
    if _strategy_and_size_changed(window):
        alerts.append("cambio_tamano_y_estrategia_en_la_misma_semana")
    if missed / expected * 100 > 2:
        alerts.append("ciclos_perdidos")
    spend = float(Decimal(tokens) * Decimal("0.042") / Decimal(1_000_000))
    return {
        "fecha": _cdmx_date(now),
        "generado_en": iso(now),
        "zona": "America/Mexico_City",
        "hora_cdmx": _cdmx_clock(now),
        "periodo": {"inicio": iso(start), "fin": iso(end)},
        "ciclos": {"corridos": finished, "esperados": expected, "perdidos": missed},
        "decisiones_por_bot": dict(decisions),
        "operaciones_simuladas": fills,
        "pnl_dia_usd": pnl_day,
        "pnl_acumulado_usd": (book or {}).get("realized_pnl_usd", pnl_day),
        "drawdown_maximo_usd": (book or {}).get("drawdown_usd", "0"),
        "vetos_por_regla": dict(vetoes),
        "rechazos_por_paso": dict(rejected),
        "gasto_jev_usd": spend,
        "tokens_jev": tokens,
        "alertas": alerts,
        "glosario": {
            "PnL": "ganancia o pérdida después de comisiones y deslizamiento (slippage)",
            "veto": "regla dura en código que bloquea una acción",
            "sombra": "la mesa decide y anota, sin crear órdenes",
            "Brier": "error cuadrático de la probabilidad; más bajo es mejor",
        },
    }


def render_daily_md(report: dict) -> str:
    lines = [
        f"# Resumen diario — {report['fecha']}",
        "",
        f"Hora de la Ciudad de México (America/Mexico_City): {report['hora_cdmx']}.",
        "Todo el dinero de este reporte es simulado.",
        "",
        f"Ciclos corridos: {report['ciclos']['corridos']} de {report['ciclos']['esperados']} esperados. Perdidos: {report['ciclos']['perdidos']}.",
        f"PnL del día (después de comisiones y slippage): {report['pnl_dia_usd']} USD.",
        f"PnL acumulado: {report['pnl_acumulado_usd']} USD. Drawdown máximo: {report['drawdown_maximo_usd']} USD.",
        f"Gasto de Jev en el periodo: {report['gasto_jev_usd']:.6f} USD.",
        "",
        "## Decisiones por bot",
    ]
    for bot, count in report["decisiones_por_bot"].items():
        lines.append(f"- {bot}: {count}")
    lines.append("")
    lines.append("## Vetos por regla")
    if not report["vetos_por_regla"]:
        lines.append("- Ninguno")
    for rule, count in report["vetos_por_regla"].items():
        lines.append(f"- {rule}: {count}")
    lines.append("")
    lines.append("## Rechazos del embudo por paso")
    if not report["rechazos_por_paso"]:
        lines.append("- Ninguno")
    for step, count in report["rechazos_por_paso"].items():
        lines.append(f"- {step}: {count}")
    lines.append("")
    lines.append("## Alertas")
    if not report["alertas"]:
        lines.append("- Ninguna")
    for alert in report["alertas"]:
        lines.append(f"- {alert}")
    lines.append("")
    lines.append("Powered by CoinGecko (datos DEX, si el conector estuvo activo). Esto no es asesoría financiera.")
    return "\n".join(lines) + "\n"


def render_calibration_md(report: dict) -> str:
    lines = [
        f"# Calibración — {report['fecha']}",
        "",
        f"Hora de la Ciudad de México (America/Mexico_City): {report['generado_en']}.",
        "Brier compara la probabilidad dicha con lo que pasó. La curva de confiabilidad agrupa esas probabilidades de 10 en 10 puntos.",
        "listo_para_simulado es una recomendación. El modo no cambia sin OK de Pedro.",
        "",
    ]
    for bot, item in report["bots"].items():
        lines.append(f"## {bot}: listo_para_simulado = {item['listo_para_simulado']}")
        for motive in item["motivos"]:
            flag = "sí" if motive["ok"] else "no"
            lines.append(f"- {motive['parametro']}: {flag}. {motive['detalle']}")
        lines.append("")
    lines.append("Powered by CoinGecko. Esto no es asesoría financiera.")
    return "\n".join(lines) + "\n"


def write_reports(root: Path, daily: dict, calibration: dict) -> dict:
    fecha = daily["fecha"]
    daily_dir = root / "reportes" / "diario"
    cal_dir = root / "reportes" / "calibracion"
    agg_dir = cal_dir / "agregados"
    for folder in (daily_dir, cal_dir, agg_dir):
        folder.mkdir(parents=True, exist_ok=True)
    (daily_dir / f"{fecha}.json").write_text(json.dumps(daily, ensure_ascii=False, indent=2), encoding="utf-8")
    (daily_dir / f"{fecha}.md").write_text(render_daily_md(daily), encoding="utf-8")
    (cal_dir / f"{fecha}.json").write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")
    (cal_dir / f"{fecha}.md").write_text(render_calibration_md(calibration), encoding="utf-8")
    (agg_dir / f"{fecha}.json").write_text(json.dumps(calibration["agregados"], ensure_ascii=False, indent=2), encoding="utf-8")
    index = {
        "fecha": fecha,
        "generado_en": daily["generado_en"],
        "diario": {"md": f"reportes/diario/{fecha}.md", "json": f"reportes/diario/{fecha}.json"},
        "calibracion": {
            "md": f"reportes/calibracion/{fecha}.md",
            "json": f"reportes/calibracion/{fecha}.json",
        },
        "alertas": daily["alertas"],
    }
    (root / "reportes" / "ultimo.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"parametro": name, "ok": bool(ok), "detalle": detail}


def _pairs_for_bot(events: list[dict], bot: str, question_id: str) -> list[tuple[float, int]]:
    outcomes = {}
    for event in events:
        if event["event_type"] != "OutcomeResolved" or event.get("bot") != bot:
            continue
        payload = event["payload"]
        if payload.get("question_id") == question_id:
            outcomes[payload["source_event"]] = payload["outcome"]
    pairs = []
    for event in events:
        if event["event_type"] != "BatteryAnswered" or event.get("bot") != bot:
            continue
        if event["event_id"] not in outcomes:
            continue
        answer = _answer(event, question_id)
        if not answer:
            continue
        probs = answer.get("probs") or {}
        outcome = outcomes[event["event_id"]]
        if "si" in probs and outcome in {"si", "no"}:
            pairs.append((float(probs["si"]), 1 if outcome == "si" else 0))
        elif probs:
            chosen = max(probs, key=probs.get)
            pairs.append((float(probs[chosen]), 1 if str(chosen) == str(outcome) else 0))
    return pairs


def _answer(event: dict, question_id: str) -> dict | None:
    for item in (event.get("payload") or {}).get("answers") or []:
        if item.get("question_id") == question_id:
            return item
    return None


def _event_bot(events, question_id) -> str:
    _ = question_id
    return ""


def _shadow_days(events: list[dict], bot: str, now: datetime) -> int:
    stamps = [_when(event) for event in events if event.get("bot") == bot and event["event_type"] == "CycleStarted" or False]
    stamps = [
        _when(event)
        for event in events
        if event.get("bot") == bot and event["event_type"] in {"PolicyDecided", "BatteryAnswered", "SnapshotComputed"}
    ]
    if not stamps:
        return 0
    if any(event.get("bot") == bot and event.get("mode") not in {"", "shadow"} for event in events):
        return 0
    return max(int((as_utc(now) - min(stamps)).total_seconds() // 86400), 0)


def _missed_pct(events, config: DeskConfig, now: datetime) -> float:
    start, end = _window(now)
    finished = sum(1 for event in events if event["event_type"] == "CycleFinished" and start <= _when(event) <= end)
    expected = max(int((end - start).total_seconds() // (config.cadence_minutes * 60)), 1)
    return max(expected - finished, 0) / expected * 100


def _window(now: datetime) -> tuple[datetime, datetime]:
    end = as_utc(now)
    return end - timedelta(days=1), end


def _cdmx_date(now: datetime) -> str:
    return as_utc(now).astimezone(CDMX).strftime("%Y-%m-%d")


def _cdmx_clock(now: datetime) -> str:
    return as_utc(now).astimezone(CDMX).strftime("%Y-%m-%d %H:%M:%S America/Mexico_City")


def _when(event: dict) -> datetime:
    return as_utc(datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")))


def _sum_pnl(events: list[dict]) -> str:
    total = Decimal("0")
    for event in events:
        if event["event_type"] == "PositionClosed":
            total += Decimal(str(event["payload"].get("pnl_usd") or "0"))
    return format(total, "f")


def _strategy_and_size_changed(events: list[dict]) -> bool:
    versions = set()
    sizes = set()
    for event in events:
        if event["event_type"] != "PolicyDecided":
            continue
        payload = event["payload"]
        versions.add(payload.get("threshold_version"))
        thresholds = payload.get("thresholds") or {}
        if "position_size_pct" in thresholds:
            sizes.add(str(thresholds["position_size_pct"]))
    return len(versions) > 1 and len(sizes) > 1


def _aggregates(questions: dict) -> dict:
    rows = {}
    for bot, body in questions.items():
        for qid, stats in body.items():
            rows[f"{bot}.{qid}"] = {
                "n": stats["n"],
                "brier_sum": None if stats["brier"] is None else stats["brier"] * stats["n"],
                "cubetas": [
                    {"desde": bucket["desde"], "n": bucket["n"], "frecuencia": bucket["frecuencia"]}
                    for bucket in stats["confiabilidad"]
                ],
            }
    return rows


def _logit(value: float) -> float:
    clipped = min(0.999, max(0.001, value))
    return __import__("math").log(clipped / (1 - clipped))
