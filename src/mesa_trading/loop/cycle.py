"""Un ciclo de la mesa. En sombra no se crea ninguna orden."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from mesa_trading.book.store import BookStore, close_position, equity_usd, open_position
from mesa_trading.broker.factory import make_broker
from mesa_trading.broker.fees import FeeSchedule
from mesa_trading.broker.sim import SimBroker
from mesa_trading.config import DeskConfig
from mesa_trading.constants import PINNED_MODEL
from mesa_trading.events import make_event
from mesa_trading.filter.funnel import bank_until, cheap, hard, still_banked
from mesa_trading.logs.sink import LogSink
from mesa_trading.models import Order, Position, Proposal
from mesa_trading.policy.decide import decide
from mesa_trading.questions.catalog import battery_for, realized_outcome
from mesa_trading.risk.engine import RiskFacts, evaluate
from mesa_trading.state.snapshot import build_snapshot
from mesa_trading.util import as_utc, client_order_id, iso

POLICY_FIELDS = {
    "gambler": ("regimen", "setup", "accion", "ejecucion_degradada"),
    "house": ("estado_rango", "flujo_toxico", "vale_cotizar", "hay_volumen"),
}


@dataclass
class DeskEnv:
    config: DeskConfig
    logs: LogSink
    book: BookStore
    connector_for: Callable[[str], Any]
    judge: Any
    policy: dict
    fees: dict[str, FeeSchedule]
    curves: dict | None = None
    wallet_source: Any = None
    token_flags: Any = None
    wallet_factory: Callable[[], Any] | None = None
    flags_factory: Callable[[], Any] | None = None
    submits: list = field(default_factory=list)


def run_cycle(env: DeskEnv, cycle_id: str, now: datetime) -> dict:
    now = as_utc(now)
    _guard_spy(env)
    if env.logs.cycle_finished(cycle_id):
        return {"idempotent": True, "orders": 0}
    if not env.book.try_lock(cycle_id, now):
        return {"locked": True, "orders": 0}
    try:
        return _run_locked(env, cycle_id, now)
    finally:
        env.book.unlock(cycle_id)


def _guard_spy(env: DeskEnv) -> None:
    spy = env.config.bots["spy"]
    if not spy.enabled:
        return
    if env.wallet_source is None and env.wallet_factory is not None:
        env.wallet_source = env.wallet_factory()
    if env.token_flags is None and env.flags_factory is not None:
        env.token_flags = env.flags_factory()
    if env.wallet_source is None or env.token_flags is None:
        raise SystemExit(2)


def _run_locked(env: DeskEnv, cycle_id: str, now: datetime) -> dict:
    state, generation = env.book.read()
    if state.started_at is None:
        state.started_at = iso(now)
    _emit(env, "CycleStarted", cycle_id, now, payload={"capital_usd": str(env.config.capital_usd)})
    resumed = _roll_day(env, state, cycle_id, now)
    funnel = _empty_funnel()
    if state.halted_until is not None and now < as_utc(state.halted_until):
        _emit(
            env,
            "DeskHalted",
            cycle_id,
            now,
            payload={"hasta": iso(state.halted_until), "regla": state.halt_rule or "perdida_diaria"},
        )
        _finish(env, state, generation, cycle_id, now, "halted", funnel)
        return {"halted": True, "orders": 0, "resumed": resumed}

    _resolve_pending(env, state, cycle_id, now)
    orders = 0
    if state.position is None:
        orders += _seek(env, state, cycle_id, now, funnel)
    else:
        orders += _manage(env, state, cycle_id, now, funnel)
    _maybe_halt(env, state, cycle_id, now)
    _finish(env, state, generation, cycle_id, now, "ok", funnel)
    return {"orders": orders, "halted": state.halted_until is not None}


def _empty_funnel() -> dict:
    return {
        "vistos": 0,
        "en_banca": 0,
        "alcanzados": {},
        "rechazados_por_paso": {},
        "rechazados_por_motivo": {},
    }


def _seek(env, state, cycle_id, now, funnel) -> int:
    orders = 0
    for bot in _entry_bots(env):
        if state.position is not None or state.halted_until is not None:
            break
        mode = env.config.bots[bot].mode
        for market in env.config.bots[bot].markets:
            if state.position is not None or state.halted_until is not None:
                break
            funnel["vistos"] += 1
            if _banked(state, bot, market, now):
                funnel["en_banca"] += 1
                continue
            outcome = _consider(env, state, bot, market, mode, cycle_id, now, funnel, managing=False)
            orders += outcome
    return orders


def _manage(env, state, cycle_id, now, funnel) -> int:
    pos = state.position
    assert pos is not None
    mode = env.config.bots[pos.bot].mode
    funnel["vistos"] += 1
    raw = _fetch(env, pos.market, now, with_retries=True)
    if raw is None:
        return _close(env, state, cycle_id, now, mode, "cierre_sin_datos", None)
    return _consider(
        env, state, pos.bot, pos.market, mode, cycle_id, now, funnel, managing=True, raw=raw
    )


def _consider(env, state, bot, market, mode, cycle_id, now, funnel, managing, raw=None) -> int:
    if raw is None:
        try:
            raw = _fetch(env, market, now, with_retries=False)
        except Exception:
            _reject(env, state, bot, market, mode, cycle_id, now, "hechos_duros", "datos_viejos", funnel)
            return 0
    if raw is None:
        return _close(env, state, cycle_id, now, mode, "cierre_sin_datos", None)
    _fill_liquidity(raw)
    if bot == "house":
        raw["inventory"] = str(state.position.qty) if state.position and state.position.market == market else "0"
    snapshot = build_snapshot(bot, market, raw, now)
    _emit(
        env,
        "SnapshotComputed",
        cycle_id,
        now,
        bot=bot,
        mode=mode,
        payload={"market": market, "hash": snapshot["hash"], "age_s": snapshot.get("age_s"), "snapshot": snapshot},
        parts=(market,),
    )
    filters = env.config.filters
    if state.position is None:
        for step_result in (
            hard(
                snapshot,
                max_age_s=env.config.snapshot_max_age_s,
                max_spread_bps=filters.max_spread_bps,
                min_liquidity_usd=filters.min_liquidity_usd,
            ),
            cheap(
                snapshot,
                notional_usd=env.config.capital_usd * env.config.risk.max_position_pct,
                min_fee_usd=env.fees[env.config.markets[market].fee_schedule].min_fee_usd,
                max_vol=filters.max_vol,
                max_fee_fraction=filters.max_fee_fraction,
            ),
        ):
            _bump(funnel["alcanzados"], step_result.step)
            if step_result.rejected:
                _reject(env, state, bot, market, mode, cycle_id, now, step_result.step, step_result.reason or "", funnel, count_reached=False)
                return 0
    _bump(funnel["alcanzados"], "bateria")
    response = env.judge.ask(cycle_id, bot, snapshot)
    mapped = _record_battery(env, state, response, bot, mode, market, cycle_id, now, snapshot)
    if mapped is None:
        return 0
    proposal = decide(
        bot,
        market,
        env.config.markets[market].kind,
        mapped,
        capital_usd=equity_usd(state, _mark(snapshot)),
        mode=mode,
        policy=env.policy,
        curves=env.curves or {},
        managing=managing,
    )
    _emit(
        env,
        "PolicyDecided",
        cycle_id,
        now,
        bot=bot,
        mode=mode,
        payload={
            "market": market,
            "action": proposal.action,
            "notional_usd": str(proposal.notional_usd),
            "threshold_version": proposal.threshold_version,
            "thresholds": proposal.thresholds,
            "reason": proposal.reason,
            "habria_hecho": proposal.action,
        },
        parts=(market, proposal.action),
    )
    _bump(funnel["alcanzados"], "politica")
    facts = _facts(env, state, snapshot, response, proposal)
    veto = evaluate(proposal, state, facts, env.config)
    _bump(funnel["alcanzados"], "riesgo")
    if veto is not None:
        _emit(
            env,
            "RiskVetoed",
            cycle_id,
            now,
            bot=bot,
            mode=mode,
            payload={"market": market, "regla": veto.rule, "detail": veto.detail},
            parts=(market, veto.rule),
        )
        _bump(funnel["rechazados_por_paso"], "riesgo")
        _bump(funnel["rechazados_por_motivo"], veto.rule)
        if veto.halt:
            state.halted_until = _next_midnight(now)
            state.halt_rule = veto.rule
            _emit(env, "DeskHalted", cycle_id, now, payload={"hasta": iso(state.halted_until), "regla": veto.rule})
        if veto.close_position and state.position is not None:
            return _close(env, state, cycle_id, now, mode, veto.rule, snapshot)
        return 0
    if proposal.action == "close" and state.position is not None:
        return _close(env, state, cycle_id, now, mode, proposal.reason, snapshot)
    if not proposal.is_entry:
        return 0
    if mode == "shadow":
        make_broker("shadow").note({"bot": bot, "market": market, "action": proposal.action})
        return 0
    return _submit(env, state, proposal, snapshot, cycle_id, now, mode)


def _submit(env, state, proposal: Proposal, snapshot, cycle_id, now, mode) -> int:
    market = proposal.market
    price = _mark(snapshot)
    if price is None or price <= 0:
        return 0
    qty = (proposal.notional_usd / price).quantize(Decimal("0.00000001"))
    side = "sell" if proposal.action == "short" else "buy"
    order = Order(
        client_order_id=client_order_id(cycle_id, proposal.bot, market, proposal.action),
        cycle_id=cycle_id,
        bot=proposal.bot,
        market=market,
        side=side,
        action=proposal.action,
        order_type="market" if proposal.action != "quote" else "limit",
        qty=qty,
        notional_usd=proposal.notional_usd,
        limit_price=(price - env.config.markets[market].tick) if proposal.action == "quote" else None,
        decision_time=now,
        reason=proposal.reason,
        kind=proposal.kind,
    )
    if order.client_order_id in state.seen_orders:
        return 0
    broker = _sim(env, market, snapshot, price)
    env.submits.append(order.client_order_id)
    _emit(env, "OrderSubmitted", cycle_id, now, bot=proposal.bot, mode=mode, payload=json_order(order), parts=(order.client_order_id, "submitted"))
    ack = broker.submit(order)
    _emit(
        env,
        "OrderAcked",
        cycle_id,
        now,
        bot=proposal.bot,
        mode=mode,
        payload={"client_order_id": ack.client_order_id, "accepted": ack.accepted, "detail": ack.detail},
        parts=(order.client_order_id, "ack"),
    )
    fills = [fill for fill in broker.fills() if fill.client_order_id == order.client_order_id]
    if not fills:
        return 0
    fill = fills[-1]
    _emit(
        env,
        "OrderFilled",
        cycle_id,
        now,
        bot=proposal.bot,
        mode=mode,
        payload={
            "client_order_id": fill.client_order_id,
            "price": str(fill.price),
            "fee_usd": str(fill.fee_usd),
            "slippage_usd": str(fill.slippage_usd),
            "price_source": fill.price_source,
        },
        parts=(order.client_order_id, "fill"),
    )
    position = Position(
        market=market,
        bot=proposal.bot,
        side="short" if proposal.action == "short" else "long",
        qty=fill.qty,
        entry_price=fill.price,
        notional_usd=proposal.notional_usd,
        opened_at=fill.filled_at,
        fees_usd=fill.fee_usd,
        slippage_usd=fill.slippage_usd,
        kind=proposal.kind,
    )
    open_position(state, position, fill.fee_usd, fill.slippage_usd)
    state.seen_orders.append(order.client_order_id)
    state.last_prices[market] = str(fill.price)
    _emit(
        env,
        "PositionOpened",
        cycle_id,
        now,
        bot=proposal.bot,
        mode=mode,
        payload={"market": market, "side": position.side, "notional_usd": str(position.notional_usd)},
        parts=(market,),
    )
    return 1


def _close(env, state, cycle_id, now, mode, reason, snapshot) -> int:
    pos = state.position
    if pos is None:
        return 0
    mark = _mark(snapshot) if snapshot else None
    if mark is None:
        raw = state.last_prices.get(pos.market)
        mark = Decimal(raw) if raw else pos.entry_price
    broker_kwargs_price = mark
    if reason == "cierre_sin_datos":
        broker = SimBroker(
            fee_schedule=env.fees[env.config.markets[pos.market].fee_schedule],
            last_prices={pos.market: mark},
            cash_usd=state.cash_usd,
        )
        price_for_order = mark
        order_reason = "cierre_sin_datos"
    else:
        broker = _sim(env, pos.market, snapshot or {"last_close": str(mark)}, mark)
        price_for_order = mark
        order_reason = reason
    action = "close"
    order = Order(
        client_order_id=client_order_id(cycle_id, pos.bot, pos.market, action),
        cycle_id=cycle_id,
        bot=pos.bot,
        market=pos.market,
        side="sell" if pos.side == "long" else "buy",
        action=action,
        order_type="market",
        qty=pos.qty,
        notional_usd=pos.qty * price_for_order,
        decision_time=now,
        reason=order_reason,
        kind=pos.kind,
    )
    if env.config.bots[pos.bot].mode == "shadow":
        make_broker("shadow").note({"close": reason, "market": pos.market})
        state.position = None
        return 0
    if order.client_order_id in state.seen_orders:
        return 0
    env.submits.append(order.client_order_id)
    _emit(env, "OrderSubmitted", cycle_id, now, bot=pos.bot, mode=mode, payload=json_order(order), parts=(order.client_order_id, "submitted"))
    ack = broker.submit(order)
    _emit(env, "OrderAcked", cycle_id, now, bot=pos.bot, mode=mode, payload={"client_order_id": ack.client_order_id, "accepted": ack.accepted}, parts=(order.client_order_id, "ack"))
    fills = [fill for fill in broker.fills() if fill.client_order_id == order.client_order_id]
    if not fills:
        return 0
    fill = fills[-1]
    pnl = close_position(state, fill.price, fill.fee_usd, fill.slippage_usd, fill.filled_at)
    state.seen_orders.append(order.client_order_id)
    state.last_prices[pos.market] = str(fill.price)
    _emit(
        env,
        "OrderFilled",
        cycle_id,
        now,
        bot=pos.bot,
        mode=mode,
        payload={"client_order_id": fill.client_order_id, "price": str(fill.price), "reason": reason, "price_source": fill.price_source},
        parts=(order.client_order_id, "fill"),
    )
    _emit(
        env,
        "PositionClosed",
        cycle_id,
        now,
        bot=pos.bot,
        mode=mode,
        payload={"market": pos.market, "pnl_usd": str(pnl), "reason": reason},
        parts=(pos.market, reason),
    )
    _ = broker_kwargs_price
    return 1


def _fetch(env, market: str, now: datetime, with_retries: bool) -> dict | None:
    spec = env.config.markets[market]
    connector = env.connector_for(market)
    attempts = 1 + (env.config.data_retries if with_retries else 0)
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return _load_market(connector, spec, market, now - timedelta(hours=6))
        except Exception as exc:
            last = exc
    if with_retries:
        return None
    if last:
        raise last
    return None


def _load_market(connector, spec, market: str, since: datetime) -> dict:
    # El producto (BTC) existe en el venue; el alias de la mesa (BTC-PERP) no.
    product = spec.product or market
    symbols = [market] if product == market else [product, market]
    last: Exception | None = None
    for symbol in symbols:
        try:
            candles = connector.candles(symbol, "5m", since)
            if not candles:
                continue
            book = connector.order_book(symbol)
            if book is None:
                book = connector.order_book(market)
            funding = connector.funding(spec.product) if spec.kind == "perp" else None
            return {"candles": candles, "order_book": book, "funding": funding}
        except Exception as exc:
            last = exc
    if last:
        raise last
    raise ConnectionError("sin velas")


def _fill_liquidity(raw: dict) -> None:
    book = raw.get("order_book") or {}
    if book.get("liquidity_usd") is not None:
        raw["order_book"] = book
        return
    notional = Decimal("0")
    for candle in raw.get("candles") or []:
        notional += Decimal(str(candle["close"])) * Decimal(str(candle.get("volume") or 0))
    if notional > 0:
        book = dict(book)
        book["liquidity_usd"] = notional
        raw["order_book"] = book


def _record_battery(env, state, response, bot, mode, market, cycle_id, now, snapshot):
    status = response.get("status")
    payload = {
        "market": market,
        "battery_id": bot,
        "status": status,
        "model_version": response.get("model_version"),
        "answers": response.get("answers"),
        "input_tokens": response.get("input_tokens", 0),
        "latency_ms": response.get("latency_ms", 0),
        "reason": response.get("reason"),
        "snapshot": snapshot,
    }
    if status == "answered":
        event = _emit(env, "BatteryAnswered", cycle_id, now, bot=bot, mode=mode, payload=payload, parts=(market,))
        battery = battery_for(bot)
        state.pending_outcomes.append(
            {
                "event_id": event["event_id"],
                "bot": bot,
                "mode": mode,
                "market": market,
                "decision_time": snapshot.get("decision_time") or iso(now),
                "entry": snapshot.get("last_close"),
                "questions": [question.id for question in battery if question.calibrable],
            }
        )
        if len(state.pending_outcomes) > 200:
            state.pending_outcomes = state.pending_outcomes[-200:]
        allowed = {question.id for question in battery}
        return {
            item["question_id"]: item
            for item in response.get("answers") or []
            if item.get("question_id") in allowed
        }
    event = "BatteryTimedOut" if status == "timeout" else "BatteryFailed"
    _emit(env, event, cycle_id, now, bot=bot, mode=mode, payload=payload, parts=(market, status or ""))
    return None


def _facts(env, state, snapshot, response, proposal: Proposal) -> RiskFacts:
    version_ok = response.get("model_version") == PINNED_MODEL and response.get("status") == "answered"
    spread = Decimal(str(snapshot["spread_bps"])) if snapshot.get("spread_bps") is not None else Decimal("100")
    liquidity = Decimal(str(snapshot["liquidity_usd"])) if snapshot.get("liquidity_usd") is not None else Decimal("0")
    schedule = env.fees[env.config.markets[proposal.market].fee_schedule]
    edge = Decimal(str(proposal.thresholds.get("expected_edge_bps", "8")))
    price = _mark(snapshot)
    range_low = Decimal(snapshot["range_low"]) if snapshot.get("range_low") else None
    range_high = Decimal(snapshot["range_high"]) if snapshot.get("range_high") else None
    configured = env.config.house_range.get(proposal.market)
    if configured is not None:
        range_low, range_high = configured.low, configured.high
    volume = Decimal(snapshot["volume_6h_vs_day"]) if snapshot.get("volume_6h_vs_day") else None
    mark = price
    equity = equity_usd(state, mark)
    return RiskFacts(
        snapshot_age_s=snapshot.get("age_s"),
        max_age_s=env.config.snapshot_max_age_s,
        model_version_ok=version_ok,
        spread_bps=spread,
        liquidity_usd=liquidity,
        fee_schedule=schedule,
        expected_edge_bps=edge,
        price=price,
        range_low=range_low,
        range_high=range_high,
        volume_ratio=volume,
        equity_usd=equity,
        day_pnl_usd=equity - state.day_start_equity_usd,
    )


def _resolve_pending(env, state, cycle_id, now) -> None:
    # El libro guarda lo que falta resolver. Releer logs/ en cada tick era lo que
    # empujaba el job por encima de su timeout cuando la bitácora crecía.
    if not state.pending_outcomes:
        return
    kept: list[dict] = []
    cache: dict[str, dict | None] = {}
    for item in state.pending_outcomes:
        decision = item.get("decision_time")
        bot = item.get("bot") or ""
        market = item.get("market") or ""
        if not decision or not market:
            continue
        decided = as_utc(decision)
        remaining: list[str] = []
        for qid in item.get("questions") or []:
            question = _question(bot, qid)
            if question is None or not question.calibrable:
                continue
            if decided + question.horizon > now:
                remaining.append(qid)
                continue
            if market not in cache:
                try:
                    cache[market] = _fetch(env, market, now, with_retries=False)
                except Exception:
                    cache[market] = None
            raw = cache[market]
            if not raw:
                remaining.append(qid)
                continue
            future = [
                candle
                for candle in raw.get("candles") or []
                if as_utc(candle["ts"]) > decided
            ]
            entry = Decimal(str(item["entry"])) if item.get("entry") else None
            outcome = realized_outcome(qid, future, entry)
            if outcome is None:
                remaining.append(qid)
                continue
            _emit(
                env,
                "OutcomeResolved",
                cycle_id,
                now,
                bot=bot,
                mode=item.get("mode") or "",
                payload={
                    "market": market,
                    "question_id": qid,
                    "outcome": outcome,
                    "source_event": item.get("event_id"),
                    "decision_time": decision,
                },
                parts=(item.get("event_id") or "", qid),
            )
        if remaining:
            nxt = dict(item)
            nxt["questions"] = remaining
            kept.append(nxt)
    state.pending_outcomes = kept[-200:]


def _question(bot: str, qid: str):
    try:
        questions = battery_for(bot)
    except KeyError:
        return None
    for question in questions:
        if question.id == qid:
            return question
    return None


def _maybe_halt(env, state, cycle_id, now) -> None:
    equity = equity_usd(state, _last_mark(state))
    if equity > state.peak_equity_usd:
        state.peak_equity_usd = equity
    loss_limit = state.day_start_equity_usd * env.config.risk.daily_loss_pct
    if equity - state.day_start_equity_usd <= -loss_limit and state.halted_until is None:
        state.halted_until = _next_midnight(now)
        state.halt_rule = "perdida_diaria"
        _emit(env, "DeskHalted", cycle_id, now, payload={"hasta": iso(state.halted_until), "regla": "perdida_diaria"})


def _roll_day(env, state, cycle_id, now) -> bool:
    day = now.strftime("%Y-%m-%d")
    if state.day_start_utc == day:
        return False
    was = state.halted_until is not None
    state.day_start_utc = day
    state.day_start_equity_usd = equity_usd(state, _last_mark(state))
    state.day_realized_pnl_usd = Decimal("0")
    state.halted_until = None
    state.halt_rule = None
    if was:
        _emit(env, "DeskResumed", cycle_id, now, payload={"dia": day})
    return was


def _entry_bots(env: DeskEnv) -> list[str]:
    names = []
    for name in ("gambler", "house"):
        if env.config.bots[name].enabled:
            names.append(name)
    if env.config.bots["spy"].enabled:
        names.append("spy")
    return names


def _banked(state, bot, market, now) -> bool:
    return still_banked(state.bank.get(f"{bot}:{market}"), now)


def _reject(env, state, bot, market, mode, cycle_id, now, step, reason, funnel, count_reached=True) -> None:
    if count_reached:
        _bump(funnel["alcanzados"], step)
    _bump(funnel["rechazados_por_paso"], step)
    _bump(funnel["rechazados_por_motivo"], reason)
    until = bank_until(reason, now)
    state.bank[f"{bot}:{market}"] = "permanent" if until is None else iso(until)
    _emit(
        env,
        "CandidateRejected",
        cycle_id,
        now,
        bot=bot,
        mode=mode,
        payload={"market": market, "step": step, "reason": reason},
        parts=(market, step, reason),
    )


def _sim(env, market, snapshot, price: Decimal) -> SimBroker:
    candles = {}
    # El SimBroker necesita la vela siguiente. El conector ya la tiene en el último fetch,
    # guardada en el snapshot no; la relectura es barata en el fixture.
    try:
        spec = env.config.markets[market]
        connector = env.connector_for(market)
        rows = connector.candles(market, "5m", None) or connector.candles(spec.product, "5m", None)
        candles[market] = rows
    except Exception:
        candles[market] = []
    schedule = env.fees[env.config.markets[market].fee_schedule]
    spread = Decimal(str(snapshot.get("spread_bps") or "2"))
    liquidity = Decimal(str(snapshot.get("liquidity_usd") or "1000000"))
    return SimBroker(
        candles=candles,
        fee_schedule=schedule,
        spread_bps=spread,
        liquidity_usd=liquidity,
        cash_usd=Decimal("1000000"),
        last_prices={market: price},
    )


def _mark(snapshot: dict | None) -> Decimal | None:
    if not snapshot or snapshot.get("last_close") is None:
        return None
    return Decimal(str(snapshot["last_close"]))


def _last_mark(state) -> Decimal | None:
    if state.position is None:
        return None
    raw = state.last_prices.get(state.position.market)
    return Decimal(raw) if raw else state.position.entry_price


def _next_midnight(now: datetime) -> datetime:
    day = as_utc(now).date()
    return datetime(day.year, day.month, day.day, tzinfo=now.tzinfo) + timedelta(days=1)


def _finish(env, state, generation, cycle_id, now, result, funnel) -> None:
    state.last_cycle_id = cycle_id
    state.last_cycle_at = iso(now)
    # El libro queda escrito antes de CycleFinished. Si el log se escribiera
    # primero y el libro fallara, el siguiente tick vería el ciclo hecho y
    # se saltaría la posición.
    env.book.write(state, generation)
    _emit(
        env,
        "CycleFinished",
        cycle_id,
        now,
        payload={
            "result": result,
            "funnel": {
                "vistos": funnel["vistos"],
                "en_banca": funnel["en_banca"],
                "alcanzados": funnel["alcanzados"],
                "rechazados_por_paso": funnel["rechazados_por_paso"],
                "rechazados_por_motivo": funnel["rechazados_por_motivo"],
            },
            "funnel_reached": funnel["alcanzados"],
            "funnel_rejected": funnel["rechazados_por_paso"],
        },
    )


def _bump(counter: dict, key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _emit(env, event_type, cycle_id, now, bot="", mode="", payload=None, parts=()) -> dict:
    event = make_event(
        event_type,
        cycle_id=cycle_id,
        occurred_at=now,
        bot=bot,
        mode=mode,
        payload=payload,
        parts=parts,
    )
    env.logs.append(event)
    return event


def json_order(order: Order) -> dict:
    return {
        "client_order_id": order.client_order_id,
        "market": order.market,
        "side": order.side,
        "action": order.action,
        "notional_usd": str(order.notional_usd),
        "reason": order.reason,
    }
