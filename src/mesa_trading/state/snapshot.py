"""Foto compacta del mercado. Solo velas ya cerradas antes del instante de decisión."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from mesa_trading.constants import TOKEN_BUDGET
from mesa_trading.util import as_utc, canonical, estimate_tokens, iso, num, q, sha256_text

SNAPSHOT_TOKEN_LIMIT = TOKEN_BUDGET
# El ciclo fija `now` al arrancar y el libro se lee unos segundos después.
# Esa diferencia no es lookahead: un libro de horas adelante sí lo es.
LIVE_QUOTE_SKEW = timedelta(seconds=90)


def build_snapshot(
    bot: str,
    market: str,
    raw: dict[str, Any],
    decision_time: datetime,
) -> dict[str, Any]:
    decision = as_utc(decision_time)
    candles = _closed_candles(raw.get("candles") or [], decision)
    book = _book_asof(raw.get("order_book"), decision)
    funding = _asof_value(raw.get("funding"), decision)
    fields = _fields_for(bot, candles, book, funding, raw, decision)
    payload = {
        "bot": bot,
        "market": market,
        "decision_time": iso(decision),
        **fields,
    }
    text = canonical(payload)
    payload_with_hash = dict(payload)
    payload_with_hash["hash"] = sha256_text(text)
    payload_with_hash["token_estimate"] = estimate_tokens(canonical(payload_with_hash))
    # El hash cubre el cuerpo sin el propio hash. Se recalcula sobre el cuerpo.
    body = {key: value for key, value in payload_with_hash.items() if key not in {"hash", "token_estimate"}}
    body_text = canonical(body)
    payload_with_hash["hash"] = sha256_text(body_text)
    payload_with_hash["token_estimate"] = estimate_tokens(canonical(body))
    return payload_with_hash


def estimate_snapshot_tokens(snapshot: dict[str, Any]) -> int:
    body = {key: value for key, value in snapshot.items() if key not in {"hash", "token_estimate"}}
    return estimate_tokens(canonical(body))


def _fields_for(bot, candles, book, funding, raw, decision) -> dict[str, Any]:
    if bot == "house":
        return _house_fields(candles, book, raw, decision)
    if bot == "spy":
        return _spy_fields(raw, decision)
    return _gambler_fields(candles, book, funding, decision)


def _gambler_fields(candles, book, funding, decision: datetime) -> dict[str, Any]:
    return {
        "ret_15m": _return(candles, decision, timedelta(minutes=15)),
        "ret_1h": _return(candles, decision, timedelta(hours=1)),
        "ret_4h": _return(candles, decision, timedelta(hours=4)),
        "vol": _realized_vol(candles),
        "imbalance": book.get("imbalance"),
        "spread_bps": book.get("spread_bps"),
        "funding": funding,
        "dist_high": _distance(candles, "high"),
        "dist_low": _distance(candles, "low"),
        "last_close": _last_close(candles),
        "liquidity_usd": book.get("liquidity_usd"),
        "volume_6h_vs_day": _volume_ratio(candles),
        "age_s": _age_s(candles, book, decision),
    }


def _house_fields(candles, book, raw, decision: datetime) -> dict[str, Any]:
    gamma = Decimal(str(raw.get("gamma", "0.1")))
    k = Decimal(str(raw.get("k", "1.5")))
    inventory = Decimal(str(raw.get("inventory", "0")))
    sigma = _sigma_decimal(candles)
    horizon = Decimal("1")
    mid = _mid_decimal(book, candles)
    reservation = None
    quote_spread = None
    if mid is not None and sigma is not None:
        reservation = mid - inventory * gamma * sigma * sigma * horizon
        quote_spread = gamma * sigma * sigma * horizon + (Decimal("2") / gamma) * _ln(Decimal("1") + gamma / k)
    band = _prior_band(candles)
    return {
        "dist_low": None if band[0] is None or mid is None else num((mid - band[0]) / mid),
        "dist_high": None if band[1] is None or mid is None else num((band[1] - mid) / mid),
        "range_low": num(band[0]),
        "range_high": num(band[1]),
        "inventory": num(inventory),
        "fill_rate": raw.get("fill_rate") if raw.get("fill_rate") is not None else None,
        "spread_bps": book.get("spread_bps"),
        "reprice_cost_bps": num(raw.get("reprice_cost_bps")) if raw.get("reprice_cost_bps") is not None else num(Decimal("1")),
        "reservation": num(reservation),
        "quote_spread": num(quote_spread),
        "last_close": _last_close(candles),
        "liquidity_usd": book.get("liquidity_usd"),
        "volume_6h_vs_day": _volume_ratio(candles),
        "age_s": _age_s(candles, book, decision),
        "vol": _realized_vol(candles),
    }


def _spy_fields(raw, decision: datetime) -> dict[str, Any]:
    """Definido para cuando el flag se encienda. El ciclo no lo llama con el flag apagado."""
    flags = raw.get("token_flags") or {}
    return {
        "hit_rate": raw.get("hit_rate"),
        "realized_pnl": raw.get("realized_pnl"),
        "hold_hours": raw.get("hold_hours"),
        "size_consistency": raw.get("size_consistency"),
        "early_entry": raw.get("early_entry"),
        "holder_concentration": flags.get("holder_concentration"),
        "mint_authority_open": flags.get("mint_authority_open"),
        "liquidity_locked": flags.get("liquidity_locked"),
        "honeypot": flags.get("honeypot"),
        "age_s": 0 if raw.get("as_of") is None else int((decision - as_utc(raw["as_of"])).total_seconds()),
    }


def _closed_candles(candles: list[dict], decision: datetime) -> list[dict]:
    closed = []
    for candle in candles:
        close_ts = as_utc(candle["close_ts"]) if "close_ts" in candle else as_utc(candle["ts"])
        if close_ts <= decision:
            closed.append(candle)
    closed.sort(key=lambda candle: as_utc(candle["ts"]))
    return closed


def _book_asof(book: dict | None, decision: datetime) -> dict[str, Any]:
    if not book:
        return {"imbalance": None, "spread_bps": None, "liquidity_usd": None, "as_of": None, "mid": None}
    as_of = book.get("as_of")
    if as_of is not None and as_utc(as_of) > decision + LIVE_QUOTE_SKEW:
        return {"imbalance": None, "spread_bps": None, "liquidity_usd": None, "as_of": None, "mid": None}
    bid = book.get("bid")
    ask = book.get("ask")
    bid_qty = book.get("bid_qty")
    ask_qty = book.get("ask_qty")
    spread = None
    mid = None
    if bid is not None and ask is not None and Decimal(str(bid)) > 0 and Decimal(str(ask)) > 0:
        bid_d = Decimal(str(bid))
        ask_d = Decimal(str(ask))
        mid = (bid_d + ask_d) / Decimal("2")
        spread = num((ask_d - bid_d) / mid * Decimal("10000"))
    imbalance = None
    if bid_qty is not None and ask_qty is not None:
        bq = Decimal(str(bid_qty))
        aq = Decimal(str(ask_qty))
        total = bq + aq
        imbalance = num((bq - aq) / total) if total > 0 else None
    return {
        "imbalance": imbalance,
        "spread_bps": spread,
        "liquidity_usd": num(book.get("liquidity_usd")) if book.get("liquidity_usd") is not None else None,
        "as_of": iso(as_utc(as_of)) if as_of is not None else None,
        "mid": mid,
    }


def _asof_value(funding, decision: datetime):
    if funding is None:
        return None
    if isinstance(funding, dict):
        as_of = funding.get("as_of")
        if as_of is not None and as_utc(as_of) > decision + LIVE_QUOTE_SKEW:
            return None
        rate = funding.get("rate")
        return num(rate) if rate is not None else None
    return num(funding)


def _price_at_or_before(candles: list[dict], when: datetime) -> Decimal | None:
    chosen = None
    for candle in candles:
        if as_utc(candle["ts"]) <= when:
            chosen = candle
    if chosen is None:
        return None
    return Decimal(str(chosen["close"]))


def _return(candles: list[dict], decision: datetime, window: timedelta) -> str | None:
    now = _price_at_or_before(candles, decision)
    then = _price_at_or_before(candles, decision - window)
    if now is None or then is None or then == 0:
        return None
    return num((now - then) / then)


def _last_close(candles: list[dict]) -> str | None:
    if not candles:
        return None
    return num(candles[-1]["close"])


def _realized_vol(candles: list[dict]) -> str | None:
    closes = [Decimal(str(candle["close"])) for candle in candles]
    if len(closes) < 3:
        return None
    rets = []
    for prev, cur in zip(closes, closes[1:]):
        if prev <= 0 or cur <= 0:
            return None
        rets.append(math.log(float(cur / prev)))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((item - mean) ** 2 for item in rets) / (len(rets) - 1)
    return num(Decimal(str(math.sqrt(var))), 6)


def _distance(candles: list[dict], side: str) -> str | None:
    if len(candles) < 2:
        return None
    last = Decimal(str(candles[-1]["close"]))
    if last <= 0:
        return None
    if side == "high":
        extreme = max(Decimal(str(candle["high"])) for candle in candles)
        return num((extreme - last) / last)
    extreme = min(Decimal(str(candle["low"])) for candle in candles)
    return num((last - extreme) / last)


def _volume_ratio(candles: list[dict]) -> str | None:
    if not candles:
        return None
    last_ts = as_utc(candles[-1]["ts"])
    vol_6h = Decimal("0")
    vol_all = Decimal("0")
    span_h = Decimal("0")
    first = as_utc(candles[0]["ts"])
    span_h = Decimal(str(max((last_ts - first).total_seconds() / 3600, 1 / 60)))
    for candle in candles:
        vol = Decimal(str(candle.get("volume") or "0"))
        vol_all += vol
        if as_utc(candle["ts"]) >= last_ts - timedelta(hours=6):
            vol_6h += vol
    if vol_all <= 0 or span_h <= 0:
        return None
    pace = vol_all / span_h * Decimal("24")
    if pace <= 0:
        return None
    return num(vol_6h / (pace * Decimal("6") / Decimal("24")))


def _age_s(candles, book, decision: datetime) -> int | None:
    stamps = []
    if candles:
        close_ts = candles[-1].get("close_ts", candles[-1]["ts"])
        stamps.append(as_utc(close_ts))
    if book.get("as_of"):
        stamps.append(as_utc(book["as_of"]))
    if not stamps:
        return None
    freshest = max(stamps)
    # Un libro leído unos segundos después del reloj del ciclo no tiene edad negativa.
    return max(int((decision - freshest).total_seconds()), 0)


def _sigma_decimal(candles) -> Decimal | None:
    text = _realized_vol(candles)
    if text is None:
        return None
    return Decimal(text)


def _mid_decimal(book, candles) -> Decimal | None:
    if book.get("mid") is not None:
        return Decimal(str(book["mid"]))
    if candles:
        return Decimal(str(candles[-1]["close"]))
    return None


def _prior_band(candles: list[dict]) -> tuple[Decimal | None, Decimal | None]:
    if len(candles) < 3:
        return None, None
    prior = candles[:-1]
    return (
        min(Decimal(str(candle["low"])) for candle in prior),
        max(Decimal(str(candle["high"])) for candle in prior),
    )


def _ln(value: Decimal) -> Decimal:
    return Decimal(str(math.log(float(value))))
