"""Un libro leído unos segundos después del reloj del ciclo no es lookahead."""

from datetime import timedelta

from mesa_trading.state.snapshot import build_snapshot
from tests.helpers import T0, raw_market


def test_book_a_few_seconds_later_keeps_spread_and_liquidity():
    raw = raw_market(T0, "70000")
    raw["order_book"]["as_of"] = T0 + timedelta(seconds=5)
    raw["funding"] = {"rate": "0.0001", "as_of": T0 + timedelta(seconds=4)}
    snapshot = build_snapshot("gambler", "BTC-PERP", raw, T0)
    assert snapshot["spread_bps"] is not None
    assert snapshot["liquidity_usd"] is not None
    assert snapshot["funding"] == "0.000100"
    assert snapshot["age_s"] == 0


def test_book_an_hour_ahead_is_dropped():
    raw = raw_market(T0, "70000")
    raw["order_book"]["as_of"] = T0 + timedelta(hours=1)
    raw["funding"] = {"rate": "0.01", "as_of": T0 + timedelta(hours=2)}
    snapshot = build_snapshot("gambler", "BTC-PERP", raw, T0)
    assert snapshot["spread_bps"] is None
    assert snapshot["liquidity_usd"] is None
    assert snapshot["funding"] is None
