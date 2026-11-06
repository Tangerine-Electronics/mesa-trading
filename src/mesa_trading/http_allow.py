"""Cliente HTTP de solo lectura con lista blanca. Rechaza antes de tocar la red."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit


class AllowlistError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    host: str
    method: str
    path: str
    kind: str  # "prefix" | "exact"


RULES: tuple[Rule, ...] = (
    Rule("api.exchange.coinbase.com", "GET", "/products/", "prefix"),
    Rule("api.geckoterminal.com", "GET", "/api/v2/", "prefix"),
    Rule("api.hyperliquid.xyz", "POST", "/info", "exact"),
)

_BLOCKED_HEADER_NAMES = frozenset(
    {
        "authorization",
        "x-api-key",
        "cb-access-key",
        "cb-access-sign",
        "cb-access-passphrase",
        "proxy-authorization",
    }
)

_COINBASE_BLOCKED = ("/orders", "/fills", "/accounts", "/conversions", "/transfers", "/profiles")


def _match(method: str, host: str, path: str) -> bool:
    for rule in RULES:
        if rule.host != host or rule.method != method:
            continue
        if rule.kind == "exact" and path == rule.path:
            return True
        if rule.kind == "prefix" and path.startswith(rule.path):
            if host == "api.exchange.coinbase.com" and any(part in path for part in _COINBASE_BLOCKED):
                return False
            return True
    return False


class HttpClient:
    """Solo hosts, métodos y rutas de la lista. Sin encabezados de autorización."""

    def __init__(self, transport=None, timeout_s: float = 8.0) -> None:
        self._transport = transport or _urllib_transport
        self.timeout_s = timeout_s

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: dict | None = None,
    ) -> tuple[int, bytes]:
        self.check(method, url, headers)
        payload = None if body is None else json.dumps(body).encode("utf-8")
        safe_headers = {"Accept": "application/json", "User-Agent": "mesa-trading/0.1 (read-only)"}
        if body is not None:
            safe_headers["Content-Type"] = "application/json"
        return self._transport(method, url, safe_headers, payload, self.timeout_s)

    @staticmethod
    def check(method: str, url: str, headers: dict[str, str] | None) -> None:
        if headers:
            for name in headers:
                if name.lower() in _BLOCKED_HEADER_NAMES:
                    raise AllowlistError(f"encabezado no permitido: {name}")
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password:
            raise AllowlistError("solo https sin credenciales en la URL")
        path = parts.path or "/"
        if not _match(method.upper(), parts.hostname or "", path):
            raise AllowlistError(f"fuera de la lista blanca: {method} {parts.hostname}{path}")


def _urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout_s: float):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
