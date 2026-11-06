from fastapi.testclient import TestClient

from mesa_trading.judge.runtime import BudgetBook, JudgeRuntime, StaticKey
from mesa_trading.judge_service.app import create_app


class Boom:
    def __init__(self):
        self.calls = 0

    def __call__(self, url, key, body, timeout):
        self.calls += 1
        return 200, {}


def test_a33_missing_key_health_and_hold(tmp_path):
    transport = Boom()
    runtime = JudgeRuntime(StaticKey(None), BudgetBook(tmp_path / "b.json"), transport)
    health = runtime.health()
    assert health["status"] == "ok"
    assert health["jev_key"] == "missing"
    result = runtime.battery("c", "gambler", {"bot": "gambler"})
    assert result["status"] == "error"
    assert result["reason"] == "no_key"
    assert transport.calls == 0
    client = TestClient(create_app(runtime))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["jev_key"] == "missing"
    battery = client.post("/v1/battery", json={"cycle_id": "c", "bot": "gambler", "battery_id": "gambler", "snapshot": {}})
    assert battery.status_code == 200
    assert battery.json()["status"] == "error"
    assert transport.calls == 0
