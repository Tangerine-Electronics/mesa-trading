"""Tiempo, JSON canónico y redondeo fijo. Mismas entradas → mismos bytes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | str) -> datetime:
    if isinstance(dt, str):
        return parse_iso(dt)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return as_utc(dt).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def q(value: Decimal | int | float | str | None, places: int = 6) -> Decimal | None:
    if value is None:
        return None
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    quantum = Decimal(10) ** -places
    return number.quantize(quantum, rounding=ROUND_HALF_EVEN)


def num(value: Decimal | int | float | str | None, places: int = 6) -> str | None:
    """Número como texto de ancho fijo. None se queda None (null en JSON)."""
    quantized = q(value, places)
    if quantized is None:
        return None
    return format(quantized, "f")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Cota superior: 1 token por cada 4 caracteres, nunca por debajo del conteo de palabras."""
    if not text:
        return 0
    by_chars = (len(text) + 3) // 4
    by_words = len(text.split())
    return max(by_chars, by_words)


def client_order_id(cycle_id: str, bot: str, market: str, action: str) -> str:
    return sha256_text(f"{cycle_id}|{bot}|{market}|{action}")[:32]


def event_id(*parts: str) -> str:
    return sha256_text("|".join(parts))[:32]
