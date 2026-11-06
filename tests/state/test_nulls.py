import json

from mesa_trading.state.snapshot import build_snapshot
from mesa_trading.util import canonical
from tests.helpers import T0, raw_market


def test_a13_missing_is_null_not_zero():
    raw = raw_market(T0, "100")
    raw["funding"] = None
    raw["order_book"] = None
    snapshot = build_snapshot("gambler", "BTC-USD", raw, T0)
    assert snapshot["funding"] is None
    assert snapshot["imbalance"] is None
    assert snapshot["spread_bps"] is None
    text = canonical({key: value for key, value in snapshot.items() if key not in {"hash", "token_estimate"}})
    payload = json.loads(text)
    assert payload["funding"] is None
    assert payload["funding"] != 0
    assert "null" in text
