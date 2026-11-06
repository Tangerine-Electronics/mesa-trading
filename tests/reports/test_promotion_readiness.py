from pathlib import Path

from mesa_trading.config import load_desk, load_promotion, repo_root
from mesa_trading.reports.build import readiness


def _stats(**overrides):
    base = {
        "shadow_days": 14,
        "min_resolved": 300,
        "min_skill": 0.02,
        "buckets_ok": True,
        "max_deviation_pp": 15,
        "missed_pct": 2,
    }
    base.update(overrides)
    return base


def test_a31_each_parameter_and_mode_stays_shadow(tmp_path):
    promo = load_promotion(repo_root() / "config" / "promotion.yaml")
    ready = readiness("gambler", _stats(), promo)
    assert ready["listo_para_simulado"] == "sí"
    cases = {
        "min_shadow_days": {"shadow_days": 13},
        "min_resolved_per_question": {"min_resolved": 299},
        "min_brier_skill": {"min_skill": 0.019},
        "min_bucket_samples": {"buckets_ok": False},
        "max_bucket_deviation_pp": {"max_deviation_pp": 15.1},
        "max_missed_cycle_pct": {"missed_pct": 2.1},
    }
    for name, override in cases.items():
        result = readiness("gambler", _stats(**override), promo)
        assert result["listo_para_simulado"] == "no"
        failed = [item["parametro"] for item in result["motivos"] if not item["ok"]]
        assert name in failed
    source = repo_root() / "config" / "desk.yaml"
    copy = Path(tmp_path) / "desk.yaml"
    copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    before = copy.read_text(encoding="utf-8")
    readiness("house", _stats(), promo)
    assert copy.read_text(encoding="utf-8") == before
    config = load_desk(copy)
    assert {bot.mode for bot in config.bots.values()} == {"shadow"}
