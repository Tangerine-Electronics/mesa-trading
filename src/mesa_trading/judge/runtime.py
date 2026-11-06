"""Una llamada a Jev por batería. Sin reintento si la pregunta está mal formada."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from mesa_trading.constants import (
    MONTHLY_BUDGET_USD,
    PINNED_MODEL,
    USD_PER_MILLION_INPUT_TOKENS,
)
from mesa_trading.questions.catalog import battery_for

JEV_URL = "https://api.typesafe.ai/v1/systemone"


class BudgetBook:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def tokens(self, month: str) -> int:
        return int(self._load().get(month, 0))

    def add(self, month: str, amount: int) -> None:
        data = self._load()
        data[month] = int(data.get(month, 0)) + int(amount)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8") or "{}")


class JudgeRuntime:
    def __init__(self, key_provider, budget: BudgetBook, transport=None, deadline_ms: int = 2000) -> None:
        self.key_provider = key_provider
        self.budget = budget
        self.transport = transport or urllib_jev
        self.deadline_ms = deadline_ms

    def health(self) -> dict:
        present = self.key_provider.load() is not None
        return {
            "status": "ok",
            "app": "mesa-trading-judge",
            "model": PINNED_MODEL,
            "jev_key": "present" if present else "missing",
            "monthly_budget_usd": str(MONTHLY_BUDGET_USD),
        }

    def battery(self, cycle_id: str, bot: str, snapshot: dict) -> dict:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        if self._over_budget(month):
            return _result("budget_exceeded", input_tokens=0, latency_ms=0, reason="budget_exceeded")
        key = self.key_provider.load()
        if not key:
            return _result("error", input_tokens=0, latency_ms=0, reason="no_key")
        questions = {q.id: q.jev_body() for q in battery_for(bot)}
        body = {"model": PINNED_MODEL, "state": _state_for_jev(snapshot), "questions": questions}
        started = time.monotonic()
        deadline_s = self.deadline_ms / 1000
        attempts = 0
        status_code = 0
        payload: dict = {}
        while True:
            attempts += 1
            remaining = deadline_s - (time.monotonic() - started)
            if remaining <= 0:
                return _result("timeout", input_tokens=0, latency_ms=_ms(started), reason="deadline")
            try:
                status_code, payload = self.transport(JEV_URL, key, body, remaining)
            except TimeoutError:
                return _result("timeout", input_tokens=0, latency_ms=_ms(started), reason="deadline")
            except Exception:
                return _result("error", input_tokens=0, latency_ms=_ms(started), reason="judge_error")
            if status_code == 429 and attempts == 1:
                continue
            break
        latency = _ms(started)
        if status_code in (400, 422):
            return _result("malformed", input_tokens=0, latency_ms=latency, reason="malformed")
        if status_code == 429:
            return _result("rate_limited", input_tokens=0, latency_ms=latency, reason="rate_limited")
        if status_code != 200:
            return _result("error", input_tokens=0, latency_ms=latency, reason="upstream")
        usage = payload.get("usage") or {}
        tokens = int(usage.get("input_tokens") or 0)
        self.budget.add(month, tokens)
        model = str(payload.get("model") or "")
        answers = []
        for question in battery_for(bot):
            raw = (payload.get("answers") or {}).get(question.id)
            if raw is None:
                continue
            answers.append(_normalize(question.id, raw))
        return _result(
            "answered",
            model_version=model,
            answers=answers,
            input_tokens=tokens,
            latency_ms=latency,
        )

    def _over_budget(self, month: str) -> bool:
        spent = Decimal(self.budget.tokens(month)) * USD_PER_MILLION_INPUT_TOKENS / Decimal(1_000_000)
        return spent >= MONTHLY_BUDGET_USD


def _state_for_jev(snapshot: dict) -> dict:
    skip = {"hash", "token_estimate"}
    return {key: value for key, value in snapshot.items() if key not in skip}


def _normalize(question_id: str, raw: dict) -> dict:
    kind = raw.get("type")
    if kind == "noul":
        yes = Decimal(str(raw.get("noul", "0")))
        return {"question_id": question_id, "probs": {"si": float(yes), "no": float(Decimal("1") - yes)}}
    if kind == "choice":
        probs = {str(key): float(value) for key, value in (raw.get("probabilities") or {}).items()}
        return {"question_id": question_id, "probs": probs}
    if kind == "score":
        probs = {str(key): float(value) for key, value in (raw.get("probabilities") or {}).items()}
        score = sum(Decimal(key) * Decimal(str(value)) for key, value in probs.items())
        return {"question_id": question_id, "probs": probs, "score": float(score)}
    raise ValueError("tipo de respuesta desconocido")


def _result(status: str, **extra) -> dict:
    base = {
        "status": status,
        "model_version": extra.pop("model_version", None),
        "answers": extra.pop("answers", []),
        "input_tokens": extra.pop("input_tokens", 0),
        "latency_ms": extra.pop("latency_ms", 0),
    }
    if "reason" in extra:
        base["reason"] = extra["reason"]
    return base


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def urllib_jev(url: str, key: str, body: dict, timeout_s: float) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "mesa-trading-judge/0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {}
        return exc.code, payload
    except TimeoutError:
        raise
    except Exception as exc:
        if "timed out" in str(exc).lower():
            raise TimeoutError from None
        raise RuntimeError("jev_unreachable") from None


class StaticKey:
    def __init__(self, value: str | None) -> None:
        self._value = value or None

    def load(self) -> str | None:
        return self._value


class EnvKey:
    def __init__(self, name: str = "MESA_JEV_KEY") -> None:
        self.name = name

    def load(self) -> str | None:
        import os

        value = os.environ.get(self.name, "").strip()
        return value or None
