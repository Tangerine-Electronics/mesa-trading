from datetime import timedelta
from decimal import Decimal

from mesa_trading.state.snapshot import build_snapshot
from mesa_trading.util import canonical
from tests.helpers import T0, raw_market


def test_a13_same_input_same_hash():
    raw = raw_market(T0, "100")
    first = build_snapshot("gambler", "BTC-USD", raw, T0)
    second = build_snapshot("gambler", "BTC-USD", raw, T0)
    assert first["hash"] == second["hash"]
    assert canonical({k: v for k, v in first.items() if k not in {"hash", "token_estimate"}}) == canonical(
        {k: v for k, v in second.items() if k not in {"hash", "token_estimate"}}
    )


def test_a13_future_candle_does_not_change_hash():
    raw = raw_market(T0, "100")
    base = build_snapshot("gambler", "BTC-USD", raw, T0)
    future = {
        "ts": T0 + timedelta(minutes=5),
        "close_ts": T0 + timedelta(minutes=10),
        "open": Decimal("999"),
        "high": Decimal("1000"),
        "low": Decimal("998"),
        "close": Decimal("999"),
        "volume": Decimal("100"),
    }
    raw["candles"].append(future)
    changed = build_snapshot("gambler", "BTC-USD", raw, T0)
    assert changed["hash"] == base["hash"]


def test_house_and_spy_snapshots_are_deterministic():
    raw = raw_market(T0, "100")
    raw["inventory"] = "0"
    raw["fill_rate"] = "0.2"
    house = build_snapshot("house", "BTC-USD", raw, T0)
    again = build_snapshot("house", "BTC-USD", raw, T0)
    assert house["hash"] == again["hash"]
    spy_raw = {
        "hit_rate": None,
        "realized_pnl": None,
        "as_of": T0,
        "token_flags": {"honeypot": None, "mint_authority_open": None, "liquidity_locked": None},
    }
    spy = build_snapshot("spy", "TOKEN", spy_raw, T0)
    assert spy["honeypot"] is None
