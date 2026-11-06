from datetime import timedelta
from decimal import Decimal

from mesa_trading.book.store import FileBookStore
from mesa_trading.loop.cycle import run_cycle
from mesa_trading.models import Position
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def test_a17_open_position_blocks_new_entries(tmp_path):
    env = make_env(tmp_path, ScriptedJudge(bullish()), connector_for(T0, future_open="70100"), mode="simulated", markets=["BTC-PERP"])
    state, generation = env.book.read()
    state.position = Position(
        market="BTC-PERP",
        bot="gambler",
        side="long",
        qty=Decimal("0.003"),
        entry_price=Decimal("70000"),
        notional_usd=Decimal("210"),
        opened_at=T0,
        kind="perp",
    )
    state.last_prices["BTC-PERP"] = "70000"
    env.book.write(state, generation)
    run_cycle(env, "ocupado", T0)
    assert env.submits == []
    again, _ = env.book.read()
    assert again.position is not None
    assert again.position.market == "BTC-PERP"


def test_a17_generation_precondition(tmp_path):
    store = FileBookStore(tmp_path, capital=Decimal("1000"), now=T0)
    first, gen = store.read()
    second, gen2 = store.read()
    assert gen == gen2
    first.cash_usd = Decimal("900")
    assert store.write(first, gen)
    second.cash_usd = Decimal("100")
    assert store.write(second, gen) is False
    saved, new_gen = store.read()
    assert saved.cash_usd == Decimal("900")
    assert new_gen == gen + 1
    assert store.try_lock("a", T0)
    assert store.try_lock("b", T0) is False
    assert store.try_lock("b", T0 + timedelta(seconds=120))
