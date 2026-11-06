import json

from fastapi.testclient import TestClient

from mesa_trading.api.app import create_app
from mesa_trading.reports.build import write_reports
from mesa_trading.storage import LocalRoot
from tests.helpers import T0


def test_a32_index_and_health(tmp_path):
    daily = {
        "fecha": "2026-11-06",
        "generado_en": "2026-11-06T18:00:00.000000Z",
        "hora_cdmx": "2026-11-06 12:00:00 America/Mexico_City",
        "zona": "America/Mexico_City",
        "periodo": {},
        "ciclos": {"corridos": 1, "esperados": 288, "perdidos": 287},
        "decisiones_por_bot": {},
        "operaciones_simuladas": [],
        "pnl_dia_usd": "0",
        "pnl_acumulado_usd": "0",
        "drawdown_maximo_usd": "0",
        "vetos_por_regla": {},
        "rechazos_por_paso": {},
        "gasto_jev_usd": 0,
        "tokens_jev": 0,
        "alertas": [],
        "glosario": {},
    }
    calibration = {
        "fecha": "2026-11-06",
        "generado_en": daily["generado_en"],
        "zona": "America/Mexico_City",
        "modelo": "jev-1.14.0",
        "preguntas": {},
        "bots": {},
        "agregados": {},
    }
    index = write_reports(tmp_path, daily, calibration)
    assert set(index) >= {"fecha", "diario", "calibracion", "alertas"}
    stored = json.loads((tmp_path / "reportes" / "ultimo.json").read_text(encoding="utf-8"))
    assert stored == index
    client = TestClient(create_app(LocalRoot(tmp_path)))
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["broker"] == "simulado"
    assert body["app"] == "mesa-trading"
    ultimo = client.get("/reportes/ultimo.json")
    assert ultimo.status_code == 200
    assert ultimo.json()["fecha"] == "2026-11-06"
    assert client.get("/reportes/diario/2026-11-06.json").status_code == 200
    assert client.get("/reportes/calibracion/2026-11-06.json").status_code == 200
    assert client.get("/estado").status_code == 200
    assert client.get("/reportes").status_code == 200
    _ = T0
