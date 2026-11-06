import json

from mesa_trading.judge.runtime import BudgetBook, JudgeRuntime, StaticKey

SECRET = "unit-test-jev-credential-value"


class Leaky:
    def __call__(self, url, key, body, timeout):
        raise RuntimeError(key)


def test_a11_secret_never_leaves_the_judge(tmp_path):
    runtime = JudgeRuntime(StaticKey(SECRET), BudgetBook(tmp_path / "b.json"), Leaky())
    result = runtime.battery("c", "gambler", {"bot": "gambler"})
    blob = json.dumps(result)
    assert SECRET not in blob
    assert result["reason"] == "judge_error"
    health = json.dumps(runtime.health())
    assert SECRET not in health
    assert "present" in health
