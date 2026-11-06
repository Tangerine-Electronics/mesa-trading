"""Conectores públicos de solo lectura. Pasan por el cliente con lista blanca."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mesa_trading.http_allow import HttpClient

COINBASE = "https://api.exchange.coinbase.com"
GECKO = "https://api.geckoterminal.com"
HYPERLIQUID = "https://api.hyperliquid.xyz"


class CoinbaseConnector:
    name = "coinbase"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def candles(self, symbol: str, interval: str, since: datetime | None = None) -> list[dict]:
        granularity = {"1m": 60, "5m": 300, "1h": 3600}.get(interval, 300)
        status, body = self.client.request("GET", f"{COINBASE}/products/{symbol}/candles?granularity={granularity}")
        if status != 200:
            raise ConnectionError(f"coinbase candles {status}")
        rows = []
        for time_s, low, high, open_, close, volume in json.loads(body):
            start = datetime.fromtimestamp(int(time_s), tz=timezone.utc)
            rows.append(_candle(start, granularity, open_, high, low, close, volume))
        rows.sort(key=lambda row: row["ts"])
        return rows

    def order_book(self, symbol: str, depth: int = 5) -> dict | None:
        status, body = self.client.request("GET", f"{COINBASE}/products/{symbol}/book?level=1")
        if status != 200:
            raise ConnectionError(f"coinbase book {status}")
        payload = json.loads(body)
        bids = payload.get("bids") or []
        asks = payload.get("asks") or []
        if not bids or not asks:
            return None
        return {
            "bid": bids[0][0],
            "ask": asks[0][0],
            "bid_qty": bids[0][1],
            "ask_qty": asks[0][1],
            "as_of": datetime.now(timezone.utc),
            "liquidity_usd": None,
        }

    def trades(self, symbol: str, since: datetime | None = None) -> list[dict]:
        status, body = self.client.request("GET", f"{COINBASE}/products/{symbol}/trades")
        if status != 200:
            raise ConnectionError(f"coinbase trades {status}")
        return json.loads(body)

    def funding(self, symbol: str) -> dict | None:
        return None

    def market_status(self) -> dict:
        return {"open": True}

    def metadata(self) -> dict:
        return {"name": self.name, "host": "api.exchange.coinbase.com"}


class GeckoTerminalConnector:
    name = "geckoterminal"

    def __init__(self, client: HttpClient | None = None, pools: dict[str, tuple[str, str]] | None = None) -> None:
        self.client = client or HttpClient()
        self.pools = pools or {}

    def candles(self, symbol: str, interval: str, since: datetime | None = None) -> list[dict]:
        network, pool = self.pools[symbol]
        aggregate = 5 if interval == "5m" else 1
        url = (
            f"{GECKO}/api/v2/networks/{network}/pools/{pool}/ohlcv/minute"
            f"?aggregate={aggregate}&limit=100&currency=usd"
        )
        status, body = self.client.request("GET", url)
        if status != 200:
            raise ConnectionError(f"geckoterminal ohlcv {status}")
        payload = json.loads(body)
        rows = []
        for item in payload.get("data", {}).get("attributes", {}).get("ohlcv_list", []):
            ts, open_, high, low, close, volume = item[:6]
            start = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            rows.append(_candle(start, aggregate * 60, open_, high, low, close, volume))
        rows.sort(key=lambda row: row["ts"])
        return rows

    def order_book(self, symbol: str, depth: int = 5) -> dict | None:
        network, pool = self.pools[symbol]
        status, body = self.client.request("GET", f"{GECKO}/api/v2/networks/{network}/pools/{pool}")
        if status != 200:
            raise ConnectionError(f"geckoterminal pool {status}")
        attrs = json.loads(body).get("data", {}).get("attributes", {})
        price = attrs.get("base_token_price_usd")
        reserve = attrs.get("reserve_in_usd")
        if price is None:
            return None
        px = Decimal(str(price))
        half = px * Decimal("0.0005")
        return {
            "bid": str(px - half),
            "ask": str(px + half),
            "bid_qty": "1",
            "ask_qty": "1",
            "as_of": datetime.now(timezone.utc),
            "liquidity_usd": reserve,
        }

    def trades(self, symbol: str, since: datetime | None = None) -> list[dict]:
        return []

    def funding(self, symbol: str) -> dict | None:
        return None

    def market_status(self) -> dict:
        return {"open": True}

    def metadata(self) -> dict:
        return {"name": self.name, "attribution": "Powered by CoinGecko"}


class HyperliquidInfoConnector:
    """Solo POST /info. Nunca llama a /exchange."""

    name = "hyperliquid"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def candles(self, symbol: str, interval: str, since: datetime | None = None) -> list[dict]:
        end = datetime.now(timezone.utc)
        start = since or (end - timedelta(hours=6))
        body = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": int(start.timestamp() * 1000),
                "endTime": int(end.timestamp() * 1000),
            },
        }
        status, raw = self._info(body)
        if status != 200:
            raise ConnectionError(f"hyperliquid candles {status}")
        rows = []
        for item in json.loads(raw):
            start_dt = datetime.fromtimestamp(int(item["t"]) / 1000, tz=timezone.utc)
            rows.append(
                _candle(start_dt, 300, item["o"], item["h"], item["l"], item["c"], item["v"])
            )
        rows.sort(key=lambda row: row["ts"])
        return rows

    def order_book(self, symbol: str, depth: int = 5) -> dict | None:
        status, raw = self._info({"type": "l2Book", "coin": symbol})
        if status != 200:
            raise ConnectionError(f"hyperliquid book {status}")
        levels = json.loads(raw).get("levels") or []
        if len(levels) < 2 or not levels[0] or not levels[1]:
            return None
        bid = levels[0][0]
        ask = levels[1][0]
        return {
            "bid": bid["px"],
            "ask": ask["px"],
            "bid_qty": bid["sz"],
            "ask_qty": ask["sz"],
            "as_of": datetime.now(timezone.utc),
            "liquidity_usd": None,
        }

    def trades(self, symbol: str, since: datetime | None = None) -> list[dict]:
        return []

    def funding(self, symbol: str) -> dict | None:
        status, raw = self._info({"type": "metaAndAssetCtxs"})
        if status != 200:
            raise ConnectionError(f"hyperliquid meta {status}")
        payload = json.loads(raw)
        universe = payload[0].get("universe", [])
        ctxs = payload[1]
        for meta, ctx in zip(universe, ctxs):
            if meta.get("name") == symbol:
                return {"rate": ctx.get("funding"), "as_of": datetime.now(timezone.utc)}
        return None

    def market_status(self) -> dict:
        return {"open": True}

    def metadata(self) -> dict:
        return {"name": self.name, "path": "/info"}

    def _info(self, body: dict) -> tuple[int, bytes]:
        if body.get("type") is None:
            raise ValueError("info sin type")
        return self.client.request("POST", f"{HYPERLIQUID}/info", body=body)


def _candle(start: datetime, seconds: int, open_, high, low, close, volume) -> dict:
    return {
        "ts": start,
        "close_ts": start + timedelta(seconds=seconds),
        "open": Decimal(str(open_)),
        "high": Decimal(str(high)),
        "low": Decimal(str(low)),
        "close": Decimal(str(close)),
        "volume": Decimal(str(volume)),
    }
