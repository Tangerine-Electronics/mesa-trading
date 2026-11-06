from decimal import Decimal

from mesa_trading.config import load_desk, load_promotion, repo_root
from mesa_trading.constants import MONTHLY_BUDGET_USD, PINNED_MODEL


def test_a29_pedro_defaults():
    config = load_desk(repo_root() / "config" / "desk.yaml")
    promo = load_promotion(repo_root() / "config" / "promotion.yaml")
    assert config.capital_usd == Decimal("1000")
    assert config.risk.max_position_pct == Decimal("0.25")
    assert config.risk.max_exposure_pct == Decimal("0.25")
    assert config.risk.daily_loss_pct == Decimal("0.05")
    assert config.risk.leverage == Decimal("1")
    assert config.risk.single_position is True
    assert config.cadence_minutes == 5
    assert {bot.mode for bot in config.bots.values()} == {"shadow"}
    assert config.bots["spy"].enabled is False
    assert config.connectors["coinbase"].enabled is False
    assert all(market.venue != "coinbase" for market in config.markets.values())
    assert config.judge.model == PINNED_MODEL
    assert config.judge.deadline_ms == 2000
    assert config.judge.monthly_budget_usd == MONTHLY_BUDGET_USD
    assert promo.min_shadow_days == 14
    assert promo.min_resolved_per_question == 300
    assert promo.min_brier_skill == Decimal("0.02")
    assert promo.min_bucket_samples == 30
    assert promo.max_bucket_deviation_pp == Decimal("15")
    assert promo.max_missed_cycle_pct == Decimal("2")
