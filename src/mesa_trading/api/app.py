"""API pública de solo lectura. No hay ningún endpoint que cambie la mesa."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from mesa_trading.config import default_desk_path, load_desk
from mesa_trading.storage import DataRoot, LocalRoot, data_root_from_env


def create_app(root: DataRoot | None = None, desk_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="mesa-trading", docs_url=None, redoc_url=None)
    store = root or data_root_from_env()
    config = load_desk(desk_path or Path(os.environ.get("MESA_DESK_CONFIG", str(default_desk_path()))))

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "app": "mesa-trading",
            "broker": "simulado",
            "modos": {name: bot.mode for name, bot in config.bots.items()},
            "version": os.environ.get("MESA_GIT_SHA", "dev"),
        }

    @app.get("/estado")
    def estado() -> dict:
        book = _json(store, "book/state.json")
        state = (book or {}).get("state") or {}
        position = state.get("position")
        return {
            "ultimo_ciclo": _latest_cycle(store),
            "posicion_abierta": position,
            "vetos_activos": {
                "halted_until": state.get("halted_until"),
                "halt_rule": state.get("halt_rule"),
            },
            "broker": "simulado",
        }

    @app.get("/reportes", response_class=HTMLResponse)
    def reportes() -> str:
        index = _json(store, "reportes/ultimo.json")
        if not index:
            return "<html><body><p>Aún no hay reporte. El dinero de esta mesa es simulado.</p></body></html>"
        daily = store.read_text(index["diario"]["md"]) or ""
        cal = store.read_text(index["calibracion"]["md"]) or ""
        body = (
            "<html><head><meta charset='utf-8'><title>Reportes mesa-trading</title></head><body>"
            f"<pre>{_escape(daily)}</pre><hr><pre>{_escape(cal)}</pre>"
            "<p>Powered by CoinGecko. Esto no es asesoría financiera.</p></body></html>"
        )
        return body

    @app.get("/reportes/ultimo.json")
    def ultimo():
        payload = _json(store, "reportes/ultimo.json")
        if payload is None:
            raise HTTPException(status_code=404, detail="sin reporte")
        return JSONResponse(payload)

    @app.get("/reportes/diario/{fecha}.json")
    def diario(fecha: str):
        return _report(store, f"reportes/diario/{fecha}.json")

    @app.get("/reportes/calibracion/{fecha}.json")
    def calibracion(fecha: str):
        return _report(store, f"reportes/calibracion/{fecha}.json")

    return app


def _report(store: DataRoot, key: str):
    payload = _json(store, key)
    if payload is None:
        raise HTTPException(status_code=404, detail="no encontrado")
    return JSONResponse(payload)


def _json(store: DataRoot, key: str) -> dict | None:
    text = store.read_text(key)
    if text is None:
        return None
    return json.loads(text)


def _latest_cycle(store: DataRoot) -> str | None:
    if isinstance(store, LocalRoot):
        files = sorted((store.root / "logs").glob("dt=*/*.jsonl")) if (store.root / "logs").exists() else []
        if not files:
            return None
        return files[-1].stem
    return None


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


app = create_app()
