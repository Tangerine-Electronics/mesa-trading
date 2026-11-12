import json

from fastapi.testclient import TestClient

from mesa_trading.api.app import create_app
from mesa_trading.storage import LocalRoot


def test_estado_reads_the_book_and_does_not_list_logs(tmp_path):
    root = LocalRoot(tmp_path)
    root.write_text(
        "book/state.json",
        json.dumps(
            {
                "state": {
                    "cash_usd": "1000",
                    "day_start_equity_usd": "1000",
                    "day_start_utc": "2026-11-12",
                    "peak_equity_usd": "1000",
                    "last_cycle_id": "20261112T171500Z",
                    "last_cycle_at": "2026-11-12T17:15:00.000000Z",
                    "closed_trades": 3,
                }
            }
        ),
    )

    class Exploding(LocalRoot):
        def list_prefix(self, prefix: str) -> list[str]:
            raise AssertionError(f"no hay que listar {prefix}")

        def read_text(self, key: str) -> str | None:
            if key.startswith("logs/"):
                raise AssertionError(key)
            return super().read_text(key)

    client = TestClient(create_app(Exploding(tmp_path)))
    response = client.get("/estado")
    assert response.status_code == 200
    body = response.json()
    assert body["ultimo_ciclo"] == "20261112T171500Z"
    assert body["ultimo_ciclo_en"] == "2026-11-12T17:15:00.000000Z"
    assert body["operaciones_cerradas"] == 3
    assert body["broker"] == "simulado"
    assert body["posicion_abierta"] is None
