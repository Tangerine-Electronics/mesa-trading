"""El fallo de staging: el libro nace unos segundos después de `now` y el filtro lo tiraba."""

from datetime import timedelta

from mesa_trading.loop.cycle import run_cycle
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def test_skewed_live_book_is_not_rejected_as_wide_spread(tmp_path):
    connector = connector_for(T0)
    for book in connector._books.values():
        book["as_of"] = T0 + timedelta(seconds=4)
    connector._funding["BTC"]["as_of"] = T0 + timedelta(seconds=4)
    judge = ScriptedJudge(bullish())
    env = make_env(tmp_path, judge, connector, mode="simulated", markets=["BTC-PERP"])
    run_cycle(env, "20261106T120000Z", T0)
    assert judge.calls == ["gambler"]
    rejected = [event for event in env.logs.all_events() if event["event_type"] == "CandidateRejected"]
    assert rejected == []
    state, _gen = env.book.read()
    assert state.last_cycle_id == "20261106T120000Z"
    assert state.pending_outcomes
    reasons = [event["payload"]["reason"] for event in rejected]
    assert "spread_ancho" not in reasons
    assert "sin_libro" not in reasons
