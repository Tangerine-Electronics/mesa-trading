"""Servicio privado del juez. Único lugar que puede leer la llave de Jev."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from mesa_trading.config import default_desk_path, load_desk
from mesa_trading.judge.runtime import BudgetBook, EnvKey, JudgeRuntime
from mesa_trading.storage import GcpSecretKey


class BatteryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: str
    bot: str
    battery_id: str
    snapshot: dict


def create_app(runtime: JudgeRuntime | None = None) -> FastAPI:
    desk = load_desk(default_desk_path())
    app = FastAPI(title="mesa-trading-judge", docs_url=None, redoc_url=None)
    engine = runtime or _runtime(desk.judge.deadline_ms, desk.judge.daily_budget_usd)

    @app.get("/health")
    def health() -> dict:
        body = engine.health()
        body["deadline_ms"] = desk.judge.deadline_ms
        return body

    @app.post("/v1/battery")
    def battery(body: BatteryIn) -> dict:
        if body.bot != body.battery_id and body.battery_id not in {body.bot, f"{body.bot}-v1"}:
            return {"status": "malformed", "model_version": None, "answers": [], "input_tokens": 0, "latency_ms": 0, "reason": "malformed"}
        return engine.battery(body.cycle_id, body.bot, body.snapshot)

    return app


def _runtime(deadline_ms: int, daily_budget_usd=None) -> JudgeRuntime:
    project = os.environ.get("GCP_PROJECT", "")
    secret_id = os.environ.get("MESA_JEV_SECRET_ID", "mesa-trading-jev-key")
    if project:
        key = GcpSecretKey(project, secret_id)
    else:
        key = EnvKey()
    bucket = os.environ.get("MESA_BUCKET", "").strip()
    if bucket:
        from mesa_trading.gcs import GcsBudgetBook

        budget = GcsBudgetBook(bucket)
    else:
        budget_path = Path(os.environ.get("MESA_BUDGET_PATH", "/tmp/mesa-trading-budget.json"))
        budget = BudgetBook(budget_path)
    return JudgeRuntime(key, budget, deadline_ms=deadline_ms, daily_budget_usd=daily_budget_usd)


app = create_app()
