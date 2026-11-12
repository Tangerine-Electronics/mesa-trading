"""El mismo comando que Cloud Run: python -m mesa_trading.cli.api, y /health responde."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_cloud_run_entrypoint_serves_health(tmp_path):
    port = _free_port()
    env = os.environ.copy()
    env["PORT"] = str(port)
    env.pop("MESA_BUCKET", None)
    env["MESA_GIT_SHA"] = "test"
    log_path = tmp_path / "api.log"
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "mesa_trading.cli.api"],
        cwd=REPO,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        body = _wait(port, proc, log_path)
    finally:
        log.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    assert body["status"] == "ok"
    assert body["broker"] == "simulado"
    assert body["version"] == "test"
    text = log_path.read_text(encoding="utf-8")
    assert f"mesa-trading-api en 0.0.0.0:{port}" in text
    assert "Uvicorn running" in text


def _wait(port: int, proc: subprocess.Popen, log_path: Path) -> dict:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + 15
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"salió {proc.returncode}\n{log_path.read_text(encoding='utf-8')}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                assert response.status == 200
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last = str(exc)
            time.sleep(0.1)
    proc.kill()
    raise AssertionError(f"sin /health: {last}\n{log_path.read_text(encoding='utf-8')}")
