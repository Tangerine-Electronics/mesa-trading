"""La bitácora de un ciclo es un solo objeto. Un 429 no mata el tick."""

import io
import json
from decimal import Decimal
from email.message import Message

import urllib.error
import urllib.request

from mesa_trading.book.store import fresh_book
from mesa_trading.gcs import GcsBookStore, GcsLogSink, _upload
from mesa_trading.logs.sink import FileLogSink
from mesa_trading.loop.cycle import run_cycle
from tests.helpers import T0, ScriptedJudge, bullish, connector_for, make_env


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://storage.example/o", code, "err", Message(), io.BytesIO(b""))


class _Resp:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body


def test_upload_retries_429_and_503_with_backoff(monkeypatch):
    codes = iter([429, 503, 200])
    posts = []

    def urlopen(req, timeout=15):
        posts.append(req.full_url)
        code = next(codes)
        if code != 200:
            raise _http_error(code)
        return _Resp(200, b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    sleeps = []
    assert _upload("bucket", "logs/dt=2026-11-12/c.jsonl", b"{}\n", "tok", sleeper=sleeps.append, rng=lambda: 0) is True
    assert len(posts) == 3
    assert sleeps == [1.0, 2.0]


def test_upload_does_not_retry_a_client_error(monkeypatch):
    def urlopen(req, timeout=15):
        raise _http_error(400)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    sleeps = []
    try:
        _upload("bucket", "k", b"{}", "tok", sleeper=sleeps.append, rng=lambda: 0, max_attempts=4)
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    else:
        raise AssertionError("debio fallar")
    assert sleeps == []


def test_many_events_upload_once_and_a_429_does_not_raise(monkeypatch, capsys):
    uploads: list[tuple[str, bytes]] = []

    def fake_upload(bucket, key, body, token, content_type="application/json", **kwargs):
        uploads.append((key, body))
        if len(uploads) == 1:
            raise _http_error(429)
        return True

    monkeypatch.setattr("mesa_trading.gcs._upload", fake_upload)
    sink = GcsLogSink("bucket", token_provider=lambda: "tok")
    for index in range(40):
        sink.append(
            {
                "event_id": f"e{index}",
                "event_type": "CycleStarted" if index else "CycleStarted",
                "occurred_at": "2026-11-12T04:05:00.000000Z",
                "correlation_id": "20261112T040500Z",
                "bot": "",
                "mode": "simulated",
                "payload": {"n": index},
            }
        )
    sink.append(
        {
            "event_id": "fin",
            "event_type": "CycleFinished",
            "occurred_at": "2026-11-12T04:05:01.000000Z",
            "correlation_id": "20261112T040500Z",
            "bot": "",
            "mode": "",
            "payload": {"result": "ok"},
        }
    )
    assert uploads == []
    sink.flush()
    assert len(uploads) == 1
    key, body = uploads[0]
    assert key == "logs/dt=2026-11-12/20261112T040500Z.jsonl"
    rows = [json.loads(line) for line in body.decode().splitlines()]
    assert len(rows) == 41
    assert rows[-1]["event_type"] == "CycleFinished"
    assert "aviso" in capsys.readouterr().err
    sink.flush()
    assert len(uploads) == 1


def test_state_write_is_one_object_and_survives_429(monkeypatch):
    posts = []

    def urlopen(req, timeout=15):
        url = req.full_url
        if "uploadType" in url:
            posts.append(url)
            if len(posts) == 1:
                raise _http_error(429)
            return _Resp(200, b"{}")
        if "alt=media" in url:
            return _Resp(200, b"{}")
        return _Resp(200, json.dumps({"generation": "4"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    store = GcsBookStore("bucket", Decimal("1000"), T0, token_provider=lambda: "tok")
    state = fresh_book(Decimal("1000"), T0)
    state.last_cycle_id = "20261112T040500Z"
    assert store.write(state, 4) is True
    assert len(posts) == 2
    assert all("state.json" in url for url in posts)


def test_cycle_with_many_events_still_finishes_if_the_log_flush_fails(tmp_path):
    class Boom(FileLogSink):
        def __init__(self, root):
            super().__init__(root)
            self.appends = 0

        def append(self, event: dict) -> bool:
            self.appends += 1
            return super().append(event)

        def flush(self) -> None:
            raise RuntimeError("429")

    env = make_env(tmp_path, ScriptedJudge(bullish()), connector_for(T0), mode="simulated", markets=["BTC-PERP"])
    env.logs = Boom(tmp_path / "logs")
    result = run_cycle(env, "20261112T040500Z", T0)
    assert result.get("idempotent") is not True
    assert env.logs.appends >= 8
    state, _gen = env.book.read()
    assert state.last_cycle_id == "20261112T040500Z"
    kinds = {event["event_type"] for event in env.logs.all_events()}
    assert "CycleFinished" in kinds
    assert "PolicyDecided" in kinds or "CandidateRejected" in kinds
