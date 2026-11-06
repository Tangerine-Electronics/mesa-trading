from mesa_trading.constants import PINNED_MODEL
from mesa_trading.judge.runtime import BudgetBook, JudgeRuntime, StaticKey
from mesa_trading.questions.catalog import battery_for


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, url, key, body, timeout):
        self.calls += 1
        assert body["model"] == PINNED_MODEL
        assert set(body["questions"]) == {question.id for question in battery_for("gambler")}
        return self.responses.pop(0)


def test_a8_one_request_per_battery(tmp_path):
    payload = {
        "model": PINNED_MODEL,
        "usage": {"input_tokens": 40},
        "answers": {
            "regimen": {"type": "choice", "choice": "tendencia", "probabilities": {"tendencia": 0.7, "reversion": 0.1, "caotico": 0.1, "otro": 0.1}},
            "presion_compra": {"type": "noul", "noul": 0.6},
            "setup": {"type": "score", "score": 2, "probabilities": {"0": 0.1, "1": 0.1, "2": 0.2, "3": 0.6}},
            "accion": {"type": "choice", "choice": "largo", "probabilities": {"largo": 0.8, "corto": 0.1, "hold": 0.1}},
            "ejecucion_degradada": {"type": "noul", "noul": 0.2},
        },
    }
    transport = Transport([(200, payload)])
    runtime = JudgeRuntime(StaticKey("k"), BudgetBook(tmp_path / "b.json"), transport)
    result = runtime.battery("c", "gambler", {"bot": "gambler", "market": "BTC-USD"})
    assert transport.calls == 1
    assert result["status"] == "answered"
    assert result["model_version"] == PINNED_MODEL
    assert len(result["answers"]) == 5


def test_a9_malformed_is_not_retried(tmp_path):
    transport = Transport([(422, {"detail": "bad"})])
    runtime = JudgeRuntime(StaticKey("k"), BudgetBook(tmp_path / "b.json"), transport)
    result = runtime.battery("c", "gambler", {"bot": "gambler"})
    assert transport.calls == 1
    assert result["status"] == "malformed"


def test_rate_limit_retries_once(tmp_path):
    payload = {"model": PINNED_MODEL, "usage": {"input_tokens": 1}, "answers": {}}
    transport = Transport([(429, {}), (200, payload)])
    runtime = JudgeRuntime(StaticKey("k"), BudgetBook(tmp_path / "b.json"), transport)
    result = runtime.battery("c", "gambler", {"bot": "gambler"})
    assert transport.calls == 2
    assert result["status"] == "answered"
