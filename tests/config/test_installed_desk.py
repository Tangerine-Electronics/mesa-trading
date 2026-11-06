"""El paquete instalado tiene que encontrar desk.yaml.

Tras ``pip install .``, ``config.py`` vive en site-packages. ``parents[2] / config``
no es el repo y el import de la API y del juez revienta antes de escuchar el puerto.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi.testclient import TestClient

from mesa_trading.api.app import create_app
from mesa_trading.config import (
    default_desk_path,
    default_fees_path,
    default_policy_path,
    default_promotion_path,
    load_desk,
    repo_root,
)

REPO = Path(__file__).resolve().parents[2]


def test_checkout_defaults_match_repo_config():
    root = repo_root()
    assert default_desk_path() == root / "config" / "desk.yaml"
    assert default_promotion_path() == root / "config" / "promotion.yaml"
    assert default_fees_path() == root / "config" / "fees.yaml"
    assert default_policy_path() == root / "config" / "policy.yaml"
    assert load_desk(default_desk_path()).cadence_minutes == 5


def test_mesa_desk_config_overrides_checkout(tmp_path, monkeypatch):
    target = tmp_path / "desk.yaml"
    target.write_text((repo_root() / "config" / "desk.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("MESA_DESK_CONFIG", str(target))
    assert default_desk_path() == target
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["broker"] == "simulado"


def test_blank_mesa_desk_config_is_unset(monkeypatch):
    monkeypatch.setenv("MESA_DESK_CONFIG", "  ")
    assert default_desk_path() == repo_root() / "config" / "desk.yaml"


def test_cwd_config_when_checkout_is_absent(tmp_path, monkeypatch):
    import mesa_trading.config as config_module

    desk = tmp_path / "config" / "desk.yaml"
    desk.parent.mkdir()
    desk.write_text((repo_root() / "config" / "desk.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(config_module, "_source_checkout_root", lambda: None)
    monkeypatch.setattr(config_module, "_bundled_file", lambda _name: None)
    monkeypatch.delenv("MESA_DESK_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    assert default_desk_path() == desk.resolve()
    assert load_desk(default_desk_path()).capital_usd is not None


def test_installed_package_serves_health(tmp_path):
    target = tmp_path / "site-packages"
    work = tmp_path / "work"
    work.mkdir()
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-build-isolation",
            "--target",
            str(target),
            str(REPO),
        ],
        cwd=work,
    )
    bundled = target / "mesa_trading" / "bundled_config" / "desk.yaml"
    assert bundled.is_file()
    env = os.environ.copy()
    for name in (
        "MESA_DESK_CONFIG",
        "MESA_PROMOTION_CONFIG",
        "MESA_FEES_CONFIG",
        "MESA_POLICY_CONFIG",
        "MESA_BUCKET",
        "MESA_JEV_KEY",
        "GCP_PROJECT",
        "PYTHONPATH",
    ):
        env.pop(name, None)
    env["PYTHONPATH"] = str(target)
    env["MESA_BUDGET_PATH"] = str(tmp_path / "budget.json")
    subprocess.check_call(
        [
            sys.executable,
            "-c",
            (
                "from mesa_trading.config import default_desk_path, default_fees_path, "
                "default_policy_path, default_promotion_path, load_desk\n"
                "from mesa_trading.broker.fees import load_fees\n"
                "from mesa_trading.policy.decide import load_policy\n"
                "paths = [default_desk_path(), default_fees_path(), default_policy_path(), default_promotion_path()]\n"
                "assert all(path.is_file() and 'bundled_config' in path.parts for path in paths), paths\n"
                "assert load_desk(paths[0]).cadence_minutes == 5\n"
                "assert 'dex_minimo' in load_fees()\n"
                "assert load_policy()['version'] == 1\n"
            ),
        ],
        cwd=work,
        env=env,
    )
    _assert_health(work, env, "mesa_trading.cli.api", {"status": "ok", "broker": "simulado"})
    judge = _assert_health(work, env, "mesa_trading.cli.judge", {"status": "ok", "jev_key": "missing"})
    assert "deadline_ms" in judge


def _assert_health(cwd: Path, env: dict[str, str], module: str, expected: dict) -> dict:
    port = _free_port()
    child_env = dict(env)
    child_env["PORT"] = str(port)
    log_path = cwd / f"{module}.log"
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        cwd=cwd,
        env=child_env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        body = _wait_health(port, proc, log_path)
    finally:
        log.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    for key, value in expected.items():
        assert body[key] == value
    return body


def _wait_health(port: int, proc: subprocess.Popen, log_path: Path) -> dict:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + 20
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"el proceso terminó con {proc.returncode}\n{log_path.read_text(encoding='utf-8')}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                assert response.status == 200
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last = str(exc)
            time.sleep(0.2)
    proc.kill()
    raise AssertionError(f"sin /health en el puerto {port}: {last}\n{log_path.read_text(encoding='utf-8')}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
