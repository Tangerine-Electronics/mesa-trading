from datetime import timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from mesa_trading.book.store import fresh_book
from mesa_trading.broker.fees import FeeSchedule, load_fees
from mesa_trading.config import load_desk, repo_root
from mesa_trading.loop.cycle import run_cycle
from mesa_trading.models import Position, Proposal
from mesa_trading.risk.engine import RiskFacts, contract_veto, evaluate
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def _facts(**kwargs) -> RiskFacts:
    base = dict(
        snapshot_age_s=1,
        max_age_s=600,
        model_version_ok=True,
        spread_bps=Decimal("1"),
        liquidity_usd=Decimal("5000000"),
        fee_schedule=FeeSchedule(taker_bps=Decimal("1"), min_fee_usd=Decimal("0"), gas_usd=Decimal("0")),
        expected_edge_bps=Decimal("40"),
        price=Decimal("100"),
        equity_usd=Decimal("1000"),
        day_pnl_usd=Decimal("0"),
    )
    base.update(kwargs)
    return RiskFacts(**base)


def _proposal(**kwargs) -> Proposal:
    base = dict(
        bot="gambler",
        market="BTC-PERP",
        action="long",
        notional_usd=Decimal("250"),
        leverage=Decimal("1"),
        kind="perp",
        threshold_version=1,
        thresholds={"expected_edge_bps": "40"},
        is_entry=True,
    )
    base.update(kwargs)
    return Proposal(**base)


def test_a16_daily_loss_halts_until_next_utc_day(tmp_path):
    judge = ScriptedJudge(bullish())
    env = make_env(tmp_path, judge, connector_for(T0), mode="simulated", markets=["BTC-PERP"])
    state, generation = env.book.read()
    state.cash_usd = Decimal("900")
    assert env.book.write(state, generation)
    run_cycle(env, "day-1", T0)
    state, _ = env.book.read()
    assert state.halted_until is not None
    assert state.halt_rule == "perdida_diaria"
    assert env.submits == []
    later = T0 + timedelta(hours=1)
    run_cycle(env, "day-1b", later)
    assert env.submits == []
    nxt = T0 + timedelta(days=1)
    run_cycle(env, "day-2", nxt)
    events = env.logs.read_cycle("day-2")
    assert any(event["event_type"] == "DeskResumed" for event in events)


def test_a20_article_fee_vetoes_twenty_dollars():
    config = load_desk(repo_root() / "config" / "desk.yaml")
    book = fresh_book(Decimal("1000"), T0)
    schedule = load_fees()["dex_minimo"]
    veto = evaluate(
        _proposal(notional_usd=Decimal("20")),
        book,
        _facts(fee_schedule=schedule, expected_edge_bps=Decimal("40")),
        config,
    )
    assert veto is not None
    assert veto.rule == "economia"


def test_a21_missing_data_closes_after_retries(tmp_path):
    from mesa_trading.connectors.fixture import FixtureConnector

    connector = FixtureConnector(fail_times=3)
    judge = ScriptedJudge(bullish())
    env = make_env(tmp_path, judge, connector, mode="simulated", markets=["BTC-PERP"])
    state, generation = env.book.read()
    state.position = Position(
        market="BTC-PERP",
        bot="gambler",
        side="long",
        qty=Decimal("0.01"),
        entry_price=Decimal("70000"),
        notional_usd=Decimal("250"),
        opened_at=T0,
        kind="perp",
    )
    state.last_prices["BTC-PERP"] = "70000"
    state.cash_usd = Decimal("750")
    env.book.write(state, generation)
    run_cycle(env, "sin-datos", T0)
    closed = env.book.read()[0]
    assert closed.position is None
    events = env.logs.all_events()
    assert any(event["event_type"] == "PositionClosed" and event["payload"]["reason"] == "cierre_sin_datos" for event in events)
    assert connector.calls >= 3


def test_direct_vetoes():
    config = load_desk(repo_root() / "config" / "desk.yaml")
    book = fresh_book(Decimal("1000"), T0)
    assert evaluate(_proposal(), book, _facts(snapshot_age_s=9999), config).rule == "datos_viejos"
    assert evaluate(_proposal(), book, _facts(day_pnl_usd=Decimal("-60")), config).rule == "perdida_diaria"
    wide = load_desk(repo_root() / "config" / "desk.yaml")
    wide.risk.max_position_pct = Decimal("0.80")
    assert evaluate(_proposal(notional_usd=Decimal("400")), fresh_book(Decimal("1000"), T0), _facts(), wide).rule == "exposicion_total"
    assert evaluate(
        _proposal(bot="house", action="hold", is_entry=False),
        fresh_book(Decimal("1000"), T0),
        _facts(price=Decimal("30"), range_low=Decimal("10"), range_high=Decimal("20")),
        config,
    ).rule == "rango"
    assert evaluate(_proposal(), book, _facts(model_version_ok=False), config).rule == "version_modelo"
    assert evaluate(_proposal(leverage=Decimal("2")), book, _facts(), config).rule == "apalancamiento"
    assert evaluate(_proposal(action="short", kind="spot"), book, _facts(), config).rule == "corto_spot"
    assert evaluate(_proposal(notional_usd=Decimal("500")), book, _facts(), config).rule == "posicion_maxima"
    book.position = Position(
        market="ETH-USD",
        bot="house",
        side="long",
        qty=Decimal("1"),
        entry_price=Decimal("100"),
        notional_usd=Decimal("100"),
        opened_at=T0,
        kind="spot",
    )
    assert evaluate(_proposal(), book, _facts(), config).rule == "exposicion_total"
    ranged = evaluate(
        _proposal(bot="house", action="hold", is_entry=False),
        book,
        _facts(price=Decimal("1"), range_low=Decimal("10"), range_high=Decimal("20")),
        config,
    )
    assert ranged.rule == "rango" and ranged.close_position
    volume = evaluate(_proposal(is_entry=False, action="hold"), book, _facts(volume_ratio=Decimal("0.05")), config)
    assert volume.rule == "salida_volumen" and volume.close_position
    assert contract_veto({"honeypot": True}).rule == "contrato"
    assert contract_veto({"mint_authority_open": True}).detail == "mint authority abierta"
    assert contract_veto({"liquidity_locked": False}) is not None
    assert contract_veto({}) is None


@given(p=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False))
@settings(max_examples=15, deadline=None)
def test_a15_no_answer_bypasses_a_veto(p, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("veto")
    response = bullish()
    for answer in response["answers"]:
        if "si" in answer["probs"]:
            answer["probs"]["si"] = p
            answer["probs"]["no"] = 1 - p
        else:
            keys = list(answer["probs"])
            share = p / max(len(keys), 1)
            answer["probs"] = {key: share for key in keys}
            if keys:
                answer["probs"][keys[0]] = 1 - share * (len(keys) - 1)
    env = make_env(tmp, ScriptedJudge(response), connector_for(T0), mode="simulated", markets=["BTC-PERP"])
    state, generation = env.book.read()
    state.cash_usd = Decimal("900")
    env.book.write(state, generation)
    run_cycle(env, "prop", T0)
    assert env.submits == []
