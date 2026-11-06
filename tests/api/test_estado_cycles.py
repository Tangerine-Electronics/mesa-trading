"""A26: /estado ve los CycleFinished del bucket, no solo un disco local."""

import json

from fastapi.testclient import TestClient

from mesa_trading.api.app import create_app
from mesa_trading.storage import LocalRoot


def test_estado_lists_finished_cycles_from_the_log(tmp_path):
    root = LocalRoot(tmp_path)
    for index in range(12):
        cycle_id = f"20261106T120{index:02d}Z"
        body = "\n".join(
            [
                json.dumps({"event_type": "CycleStarted", "correlation_id": cycle_id}),
                json.dumps({"event_type": "CycleFinished", "correlation_id": cycle_id}),
            ]
        )
        root.write_text(f"logs/dt=2026-11-06/{cycle_id}.jsonl", body + "\n")
    client = TestClient(create_app(root))
    payload = client.get("/estado").json()
    assert payload["ultimo_ciclo"] == "20261106T12011Z"
    assert payload["ciclos_terminados"] == 12
    assert len(payload["muestra_ciclos"]) == 12
    assert payload["muestra_ciclos"][0] == "20261106T12000Z"
