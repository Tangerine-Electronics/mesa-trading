from mesa_trading.state.snapshot import SNAPSHOT_TOKEN_LIMIT, build_snapshot, estimate_snapshot_tokens
from tests.helpers import T0, raw_market


def test_a13_snapshots_fit_in_400_tokens():
    raw = raw_market(T0, "70000")
    raw["inventory"] = "0"
    for bot in ("gambler", "house"):
        snapshot = build_snapshot(bot, "BTC-USD", raw, T0)
        assert estimate_snapshot_tokens(snapshot) <= SNAPSHOT_TOKEN_LIMIT
