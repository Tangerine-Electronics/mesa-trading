"""Un ciclo y termina. Valida la configuración antes de cualquier red."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mesa_trading.broker.fees import load_fees
from mesa_trading.cli.stores import open_book, open_logs
from mesa_trading.config import default_desk_path, load_desk
from mesa_trading.connectors.fixture import FixtureConnector
from mesa_trading.connectors.live import CoinbaseConnector, GeckoTerminalConnector, HyperliquidInfoConnector
from mesa_trading.http_allow import HttpClient
from mesa_trading.loop.cycle import DeskEnv, run_cycle
from mesa_trading.policy.decide import load_policy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mesa-tick")
    parser.add_argument("--config", default=str(default_desk_path()))
    parser.add_argument("--data-dir", default=os.environ.get("MESA_DATA_DIR", "/tmp/mesa-trading"))
    parser.add_argument("--cycle-id", default="")
    parser.add_argument("--fixture", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_desk(Path(args.config))
    except Exception as exc:
        print(f"configuracion invalida: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    if config.bots["spy"].enabled:
        print("spy encendido sin fuentes de billetera", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    cycle_id = args.cycle_id or now.strftime("%Y%m%dT%H%M%SZ")
    data = Path(args.data_dir)
    if args.fixture:
        connector = FixtureConnector()

        def connector_for(_market: str):
            return connector
    else:
        client = HttpClient()
        pools = {
            name: (market.network, market.pool)
            for name, market in config.markets.items()
            if market.venue == "geckoterminal" and market.pool
        }
        coinbase = CoinbaseConnector(client)
        gecko = GeckoTerminalConnector(client, pools)
        hyper = HyperliquidInfoConnector(client)
        by_venue = {"coinbase": coinbase, "geckoterminal": gecko, "hyperliquid": hyper}

        def connector_for(market: str):
            venue = config.markets[market].venue
            if not config.connectors[venue].enabled:
                raise ConnectionError(f"conector apagado: {venue}")
            return by_venue[venue]

    judge_url = os.environ.get("MESA_JUDGE_URL", "").strip()
    if judge_url:
        judge = RemoteJudge(judge_url)
    else:
        judge = LocalHoldJudge()
    env = DeskEnv(
        config=config,
        logs=open_logs(str(data)),
        book=open_book(str(data), config.capital_usd, now),
        connector_for=connector_for,
        judge=judge,
        policy=load_policy(),
        fees=load_fees(),
    )
    run_cycle(env, cycle_id, now)
    return 0


class LocalHoldJudge:
    """Sin URL de judge: no llama a Jev y la mesa hace hold."""

    def ask(self, cycle_id: str, bot: str, snapshot: dict) -> dict:
        _ = (cycle_id, bot, snapshot)
        return {
            "status": "error",
            "model_version": None,
            "answers": [],
            "input_tokens": 0,
            "latency_ms": 0,
            "reason": "no_key",
        }


class RemoteJudge:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")

    def ask(self, cycle_id: str, bot: str, snapshot: dict) -> dict:
        import json
        import urllib.request

        body = json.dumps(
            {"cycle_id": cycle_id, "bot": bot, "battery_id": bot, "snapshot": _plain(snapshot)}
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        token = os.environ.get("MESA_JUDGE_TOKEN", "").strip()
        if not token:
            token = _identity_token(self.url)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.url + "/v1/battery", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=2.5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return {"status": "error", "model_version": None, "answers": [], "input_tokens": 0, "latency_ms": 0, "reason": "judge_error"}


def _identity_token(audience: str) -> str:
    import json
    import urllib.request

    url = (
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
        f"?audience={audience}"
    )
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    try:
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.read().decode("utf-8")
    except Exception:
        return ""


def _plain(value):
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


if __name__ == "__main__":
    raise SystemExit(main())
