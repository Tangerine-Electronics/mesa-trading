"""Calibración, Brier y resumen diario. El reporte recomienda; no cambia el modo."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from mesa_trading.config import DeskConfig, PromotionConfig
from mesa_trading.constants import ESTIMATED_INPUT_TOKENS_PER_CALL
from mesa_trading.questions.catalog import battery_for
from mesa_trading.filter.funnel import silent_step_alerts
from mesa_trading.util import as_utc, iso

CDMX = ZoneInfo("America/Mexico_City")
# Ids de pares ya contados. El reporte solo relee ~26 h, así que con esto basta
# para no duplicar y pares.json no crece sin techo.
PAIR_ID_CAP = 10000
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


def build_calibration(
    events: list[dict],
    promo: PromotionConfig,
    config: DeskConfig,
    now: datetime,
    pair_store: dict | None = None,
) -> dict:
    store = update_pair_store(pair_store, events)
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
            raw_pairs = ((store.get("pares") or {}).get(bot) or {}).get(qid) or []
            pairs = [(float(item[0]), int(item[1])) for item in raw_pairs]
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
        "pair_store": store,
    }


def build_daily(events: list[dict], config: DeskConfig, now: datetime, book: dict | None = None) -> dict:
    start, end = _window(now)
    window = [event for event in events if start <= _when(event) <= end]
    decisions: dict[str, int] = defaultdict(int)
    vetoes: dict[str, int] = defaultdict(int)
    rejected: dict[str, int] = defaultdict(int)
    motivos: dict[str, int] = defaultdict(int)
    reached: dict[str, int] = defaultdict(int)
    judge_status: dict[str, int] = defaultdict(int)
    fills = []
    tokens = 0
    finished = 0
    halted = []
    seen = 0
    banked = 0
    judge_calls = 0
    for event in window:
        kind = event["event_type"]
        payload = event.get("payload") or {}
        if kind == "PolicyDecided":
            decisions[event.get("bot") or "?"] += 1
        elif kind == "RiskVetoed":
            vetoes[payload.get("regla") or "?"] += 1
        elif kind == "CandidateRejected":
            rejected[payload.get("step") or "?"] += 1
            motivos[payload.get("reason") or "?"] += 1
        elif kind == "CycleFinished":
            finished += 1
            funnel = payload.get("funnel") or {}
            seen += int(funnel.get("vistos") or 0)
            banked += int(funnel.get("en_banca") or 0)
            for step, count in (funnel.get("alcanzados") or payload.get("funnel_reached") or {}).items():
                reached[step] += int(count)
        elif kind == "OrderFilled":
            fills.append(payload)
        elif kind == "BatteryAnswered":
            judge_calls += 1
            judge_status["answered"] += 1
            tokens += int(payload.get("input_tokens") or 0)
        elif kind == "BatteryTimedOut":
            judge_calls += 1
            judge_status["timeout"] += 1
        elif kind == "BatteryFailed":
            judge_calls += 1
            judge_status[str(payload.get("reason") or payload.get("status") or "error")] += 1
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
    if judge_status.get("no_key"):
        alerts.append("juez_sin_llave")
    price = config.judge.price_usd_per_million_input_tokens
    spend = float(Decimal(tokens) * price / Decimal(1_000_000))
    costo = _cost_ceiling(config)
    embudo = {
        "candidatos_vistos": seen,
        "en_banca": banked,
        "rechazados_por_paso": dict(rejected),
        "rechazados_por_motivo": dict(motivos),
        "alcanzados_por_paso": dict(reached),
        "evaluados_por_juez": judge_calls,
        "juez_por_estado": dict(judge_status),
        "decisiones": int(sum(decisions.values())),
        "operaciones_simuladas": len(fills),
    }
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
        "rechazos_por_motivo": dict(motivos),
        "embudo": embudo,
        "filtros": {
            "max_spread_bps": str(config.filters.max_spread_bps),
            "min_liquidity_usd": str(config.filters.min_liquidity_usd),
            "max_vol": str(config.filters.max_vol),
            "max_fee_fraction": str(config.filters.max_fee_fraction),
        },
        "gasto_jev_usd": spend,
        "gasto_jev_tope_diario_usd": float(config.judge.daily_budget_usd),
        "gasto_jev_tope_mensual_usd": float(config.judge.monthly_budget_usd),
        "costo_estimado": costo,
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
        _cost_line(report),
        "",
        "## Embudo",
    ]
    embudo = report.get("embudo") or {}
    lines.append(
        "Candidatos vistos: {vistos}. En banca: {banca}. Rechazados: {rech}. "
        "Evaluados por el juez: {juez}. Decisiones: {dec}. Operaciones simuladas: {ops}.".format(
            vistos=embudo.get("candidatos_vistos", 0),
            banca=embudo.get("en_banca", 0),
            rech=sum((embudo.get("rechazados_por_paso") or report.get("rechazos_por_paso") or {}).values()),
            juez=embudo.get("evaluados_por_juez", 0),
            dec=embudo.get("decisiones", sum((report.get("decisiones_por_bot") or {}).values())),
            ops=embudo.get("operaciones_simuladas", len(report.get("operaciones_simuladas") or [])),
        )
    )
    lines.append("")
    lines.append("## Decisiones por bot")
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
    lines.append("## Rechazos por motivo")
    motivos = report.get("rechazos_por_motivo") or {}
    if not motivos:
        lines.append("- Ninguno")
    for reason, count in motivos.items():
        lines.append(f"- {reason}: {count}")
    lines.append("")
    veredicto = report.get("veredicto")
    if veredicto:
        lines.append("## Veredicto de la estrategia")
        lines.append(f"Estado: {veredicto['estado']}.")
        lines.append(veredicto["nota"])
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
    calibration = {key: value for key, value in calibration.items() if key != "pair_store"}
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


def update_pair_store(store: dict | None, events: list[dict]) -> dict:
    """Acumula pares (probabilidad, acierto) sin contar dos veces el mismo evento."""
    current = {
        "ids": list((store or {}).get("ids") or []),
        "pares": {
            bot: {qid: [list(row) for row in rows] for qid, rows in body.items()}
            for bot, body in ((store or {}).get("pares") or {}).items()
        },
    }
    seen = set(current["ids"])
    outcomes: dict[tuple[str, str, str], str] = {}
    for event in events:
        if event.get("event_type") != "OutcomeResolved":
            continue
        payload = event.get("payload") or {}
        qid = payload.get("question_id")
        source = payload.get("source_event")
        bot = event.get("bot") or ""
        if qid and source:
            outcomes[(bot, source, qid)] = str(payload.get("outcome"))
    for event in events:
        if event.get("event_type") != "BatteryAnswered":
            continue
        bot = event.get("bot") or ""
        if bot not in POLICY_QUESTIONS:
            continue
        for question in battery_for(bot):
            qid = question.id
            key = f"{event.get('event_id')}:{qid}"
            if key in seen:
                continue
            outcome = outcomes.get((bot, event.get("event_id") or "", qid))
            if outcome is None:
                continue
            pair = _pair(_answer(event, qid), outcome)
            if pair is None:
                continue
            seen.add(key)
            current["ids"].append(key)
            current["pares"].setdefault(bot, {}).setdefault(qid, []).append([pair[0], pair[1]])
    if len(current["ids"]) > PAIR_ID_CAP:
        current["ids"] = current["ids"][-PAIR_ID_CAP:]
    return current


def apply_verdict(
    daily: dict,
    calibration: dict,
    promo: PromotionConfig,
    *,
    closed_trades: int,
    started_at: str | None,
    capital_usd: Decimal,
    max_drawdown_usd: Decimal,
    now: datetime,
) -> dict:
    """Go / no-go de la estrategia. No cambia el modo de ningún bot."""
    skills = []
    for bot, policy_qids in POLICY_QUESTIONS.items():
        questions = (calibration.get("preguntas") or {}).get(bot) or {}
        for qid in policy_qids:
            skill_value = (questions.get(qid) or {}).get("skill")
            if skill_value is not None:
                skills.append(float(skill_value))
    min_skill = min(skills) if skills else None
    days = 0.0
    if started_at:
        started = as_utc(datetime.fromisoformat(started_at.replace("Z", "+00:00")))
        days = max((as_utc(now) - started).total_seconds() / 86400, 0.0)
    rate = (closed_trades / days) if days >= 1 / 24 and closed_trades else 0.0
    remaining = max(int(promo.min_closed_trades) - int(closed_trades), 0)
    days_left = (remaining / rate) if rate > 0 else None
    pnl = Decimal(str(daily.get("pnl_acumulado_usd") or "0"))
    # El corte usa el peor pico-a-valle guardado, no el hueco que queda ahora
    # si el capital ya rebotó.
    drawdown_pct = (max_drawdown_usd / capital_usd) if capital_usd else Decimal("0")
    sample_ok = closed_trades >= promo.min_closed_trades and days >= promo.min_shadow_days
    skill_ok = min_skill is not None and min_skill >= float(promo.min_brier_skill)
    pnl_ok = pnl > promo.min_pnl_usd
    drawdown_hit = drawdown_pct > promo.max_drawdown_pct
    if drawdown_hit:
        estado = "no_go"
    elif not sample_ok:
        estado = "insuficiente"
    elif pnl_ok and skill_ok:
        estado = "go_tentativo"
    elif (not pnl_ok) or (min_skill is not None and min_skill <= 0):
        estado = "no_go"
    else:
        estado = "insuficiente"
    if rate > 0:
        ritmo = (
            f"A este ritmo ({rate:.2f} cierres por día) faltan cerca de {days_left:.0f} días "
            f"para las {promo.min_closed_trades} operaciones."
        )
    else:
        ritmo = (
            "Todavía no hay ritmo de cierres. Con una sola posición, unas 10 operaciones al día "
            f"juntan {promo.min_closed_trades} en ~20 días; unas 2 al día, en ~100 días."
        )
    nota = (
        f"Muestra: {closed_trades} cierres en {days:.1f} días (mínimo {promo.min_closed_trades} cierres "
        f"y {promo.min_shadow_days} días). PnL acumulado después de comisiones y slippage: {pnl} USD. "
        f"Skill mínimo de Brier en preguntas de política: {min_skill}. "
        f"Drawdown máximo: {drawdown_pct * 100:.2f}% del capital (corte {promo.max_drawdown_pct * 100:.0f}%). "
        f"{ritmo} "
        "GO tentativo exige la muestra, PnL > 0 y skill ≥ "
        f"{promo.min_brier_skill}. NO-GO si, ya con la muestra, el PnL no es positivo o el skill es ≤ 0, "
        "o antes si el drawdown pasa el corte. GO tentativo no autoriza dinero real ni un broker real."
    )
    daily["veredicto"] = {
        "estado": estado,
        "operaciones_cerradas": int(closed_trades),
        "min_operaciones": int(promo.min_closed_trades),
        "dias_observados": round(days, 2),
        "min_dias": int(promo.min_shadow_days),
        "cierres_por_dia": None if rate <= 0 else round(rate, 3),
        "dias_estimados_para_muestra": None if days_left is None else round(days_left, 1),
        "pnl_acumulado_usd": format(pnl, "f"),
        "brier_skill_min": min_skill,
        "drawdown_pct": float(drawdown_pct),
        "nota": nota,
    }
    return daily


def _cost_ceiling(config: DeskConfig) -> dict:
    markets = 0
    for name in ("gambler", "house"):
        bot = config.bots[name]
        if bot.enabled:
            markets += len(bot.markets)
    cycles = int(24 * 60 / config.cadence_minutes)
    calls = markets * cycles
    tokens = calls * ESTIMATED_INPUT_TOKENS_PER_CALL
    price = config.judge.price_usd_per_million_input_tokens
    usd = float(Decimal(tokens) * price / Decimal(1_000_000))
    return {
        "mercados": markets,
        "ciclos_por_dia": cycles,
        "llamadas_techo": calls,
        "tokens_por_llamada": ESTIMATED_INPUT_TOKENS_PER_CALL,
        "usd_techo": round(usd, 4),
        "usd_tope_diario": float(config.judge.daily_budget_usd),
        "usd_tope_mensual": float(config.judge.monthly_budget_usd),
        "nota": (
            f"Techo si cada ciclo manda los {markets} mercados al juez y ninguno abre posición: "
            f"{calls} llamadas × {ESTIMATED_INPUT_TOKENS_PER_CALL} tokens × {price} USD por millón "
            f"= {usd:.4f} USD/día. Un snapshot real de BTC midió ~450 tokens; 800 es colchón. "
            f"El tope diario es {config.judge.daily_budget_usd} USD y el mensual sigue en "
            f"{config.judge.monthly_budget_usd} USD. La mesa deja de llamar a Jev al cruzar cualquiera."
        ),
    }


def _cost_line(report: dict) -> str:
    costo = report.get("costo_estimado") or {}
    if not costo:
        return ""
    return (
        f"Costo estimado (techo): {costo.get('usd_techo')} USD/día. "
        f"Tope diario: {costo.get('usd_tope_diario')} USD. Tope mensual: {costo.get('usd_tope_mensual')} USD."
    )


def _pair(answer: dict | None, outcome: str) -> tuple[float, int] | None:
    if not answer:
        return None
    probs = answer.get("probs") or {}
    if "si" in probs and outcome in {"si", "no"}:
        return (float(probs["si"]), 1 if outcome == "si" else 0)
    if not probs:
        return None
    chosen = max(probs, key=probs.get)
    return (float(probs[chosen]), 1 if str(chosen) == str(outcome) else 0)


def _logit(value: float) -> float:
    clipped = min(0.999, max(0.001, value))
    return __import__("math").log(clipped / (1 - clipped))
