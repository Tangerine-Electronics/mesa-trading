"""Utilidades de prueba. No salen a la red."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from mesa_trading.book.store import FileBookStore
from mesa_trading.broker.fees import load_fees
from mesa_trading.config import DeskConfig, load_desk
from mesa_trading.connectors.fixture import FixtureConnector
from mesa_trading.constants import PINNED_MODEL
from mesa_trading.logs.sink import FileLogSink
from mesa_trading.loop.cycle import DeskEnv
from mesa_trading.policy.decide import load_policy

T0 = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def desk() -> DeskConfig:
    return load_desk(Path(__file__).resolve().parents[1] / "config" / "desk.yaml")


def series(start: datetime, n: int = 20, price: str = "100", volume: str = "20") -> list[dict]:
    rows = []
    px = Decimal(price)
    for index in range(n):
        ts = start + timedelta(minutes=5 * index)
        rows.append(
            {
                "ts": ts,
                "close_ts": ts + timedelta(minutes=5),
                "open": px,
                "high": px + Decimal("0.2"),
                "low": px - Decimal("0.2"),
                "close": px,
                "volume": Decimal(volume),
            }
        )
    return rows


def book_quote(as_of: datetime, mid: str = "100") -> dict:
    mid_d = Decimal(mid)
    return {
        "bid": str(mid_d - Decimal("0.01")),
        "ask": str(mid_d + Decimal("0.01")),
        "bid_qty": "40",
        "ask_qty": "40",
        "as_of": as_of,
        "liquidity_usd": "5000000",
    }


def raw_market(decision: datetime, price: str = "100", extra: list[dict] | None = None) -> dict:
    start = decision - timedelta(hours=5)
    candles = series(start, 60, price)
    for candle in candles:
        candle["close_ts"] = candle["ts"] + timedelta(minutes=5)
    closed = [candle for candle in candles if candle["close_ts"] <= decision]
    if extra:
        closed = candles + extra
    return {"candles": closed if extra is None else candles + extra, "order_book": book_quote(decision, price), "funding": None}


class ScriptedJudge:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[str] = []

    def ask(self, cycle_id: str, bot: str, snapshot: dict) -> dict:
        self.calls.append(bot)
        return self.response


def bullish(model: str = PINNED_MODEL) -> dict:
    return {
        "status": "answered",
        "model_version": model,
        "input_tokens": 120,
        "latency_ms": 15,
        "answers": [
            {"question_id": "regimen", "probs": {"tendencia": 0.9, "reversion": 0.04, "caotico": 0.03, "otro": 0.03}},
            {"question_id": "presion_compra", "probs": {"si": 0.8, "no": 0.2}},
            {"question_id": "setup", "probs": {"0": 0.0, "1": 0.0, "2": 0.2, "3": 0.8}, "score": 2.8},
            {"question_id": "accion", "probs": {"largo": 0.85, "corto": 0.1, "hold": 0.05}},
            {"question_id": "ejecucion_degradada", "probs": {"si": 0.05, "no": 0.95}},
            {"question_id": "estado_rango", "probs": {"dentro": 0.8, "borde": 0.1, "rompiendo": 0.05, "otro": 0.05}},
            {"question_id": "flujo_toxico", "probs": {"si": 0.1, "no": 0.9}},
            {"question_id": "vale_cotizar", "probs": {"0": 0.0, "1": 0.0, "2": 0.3, "3": 0.7}, "score": 2.7},
            {"question_id": "hay_volumen", "probs": {"si": 0.9, "no": 0.1}},
        ],
    }


def make_env(tmp: Path, judge, connector, *, mode: str = "shadow", markets: list[str] | None = None) -> DeskEnv:
    config = desk()
    for bot in config.bots.values():
        bot.mode = mode  # type: ignore[assignment]
    if markets is not None:
        config.bots["gambler"].markets = markets
        config.bots["house"].enabled = False
    return DeskEnv(
        config=config,
        logs=FileLogSink(tmp / "logs"),
        book=FileBookStore(tmp / "book", capital=config.capital_usd, now=T0),
        connector_for=lambda _market: connector,
        judge=judge,
        policy=load_policy(),
        fees=load_fees(),
        curves={
            "gambler.regimen": {"a": "1", "b": "0"},
            "gambler.setup": {"a": "1", "b": "0"},
            "gambler.accion": {"a": "1", "b": "0"},
            "gambler.ejecucion_degradada": {"a": "1", "b": "0"},
            "gambler.presion_compra": {"a": "1", "b": "0"},
            "house.estado_rango": {"a": "1", "b": "0"},
            "house.flujo_toxico": {"a": "1", "b": "0"},
            "house.vale_cotizar": {"a": "1", "b": "0"},
            "house.hay_volumen": {"a": "1", "b": "0"},
        },
    )


def connector_for(decision: datetime, price: str = "70000", future_open: str | None = None) -> FixtureConnector:
    count = 60
    start = decision - timedelta(minutes=5 * count)
    candles = series(start, count, price, volume="30")
    if future_open is not None:
        ts = decision + timedelta(minutes=1)
        px = Decimal(future_open)
        candles.append(
            {
                "ts": ts,
                "close_ts": ts + timedelta(minutes=5),
                "open": px,
                "high": px + 1,
                "low": px - 1,
                "close": px,
                "volume": Decimal("30"),
            }
        )
    return FixtureConnector(
        candles={"BTC-PERP": candles, "BTC": candles},
        books={"BTC-PERP": book_quote(decision, price), "BTC": book_quote(decision, price)},
        funding={"BTC": {"rate": "0.0001", "as_of": decision}},
    )
