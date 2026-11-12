"""Libro y bitácora en Cloud Storage, con precondición de generación."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mesa_trading.book.store import BookStore, fresh_book
from mesa_trading.logs.sink import LogSink
from mesa_trading.models import BookState
from mesa_trading.storage import metadata_token
from mesa_trading.util import as_utc, iso


class GcsLogSink(LogSink):
    def __init__(self, bucket: str, token_provider=None) -> None:
        self.bucket = bucket
        self.token_provider = token_provider or metadata_token

    def append(self, event: dict) -> bool:
        key = _log_key(event)
        token = self.token_provider()
        current, _gen = _download(self.bucket, key, token)
        rows = []
        if current:
            rows = [json.loads(line) for line in current.decode("utf-8").splitlines() if line.strip()]
        if any(row.get("event_id") == event["event_id"] for row in rows):
            return False
        rows.append(event)
        body = "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows)
        _upload(self.bucket, key, body.encode("utf-8"), token, content_type="application/x-ndjson")
        return True

    def cycle_finished(self, cycle_id: str) -> bool:
        return any(row["event_type"] == "CycleFinished" for row in self.read_cycle(cycle_id))

    def read_cycle(self, cycle_id: str) -> list[dict]:
        # Una sola llave. Listar logs/ baja la primera página (1000) y, con el
        # tiempo, el tick se pasa el timeout antes de CycleFinished.
        key = cycle_log_key(cycle_id)
        if key is None:
            return []
        body, _gen = _download(self.bucket, key, self.token_provider())
        if not body:
            return []
        return _parse_jsonl(body)

    def all_events(self) -> list[dict]:
        # El reporte pide events_between. Esto existe para no recorrer el bucket entero.
        end = datetime.now(timezone.utc)
        return self.events_between(end - timedelta(days=2), end)

    def events_between(self, start: datetime, end: datetime) -> list[dict]:
        token = self.token_provider()
        names: list[str] = []
        for day in _days_between(start, end):
            for name in _list(self.bucket, f"logs/dt={day}/", token):
                if name.endswith(".jsonl"):
                    names.append(name)
        rows: list[dict] = []
        for body in _download_many(self.bucket, names, token):
            if not body:
                continue
            for row in _parse_jsonl(body):
                when = as_utc(datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00")))
                if as_utc(start) <= when <= as_utc(end):
                    rows.append(row)
        return rows


class GcsBookStore(BookStore):
    def __init__(self, bucket: str, capital: Decimal, now: datetime, token_provider=None) -> None:
        self.bucket = bucket
        self.token_provider = token_provider or metadata_token
        self.capital = capital
        self.now = now

    def read(self) -> tuple[BookState, int]:
        token = self.token_provider()
        body, generation = _download(self.bucket, "book/state.json", token)
        if body is None or generation is None:
            state = fresh_book(self.capital, self.now)
            _upload(self.bucket, "book/state.json", _dump(state).encode("utf-8"), token, if_generation_match=0)
            body, generation = _download(self.bucket, "book/state.json", token)
        payload = json.loads(body.decode("utf-8"))
        return BookState.model_validate(payload["state"]), int(generation or 0)

    def write(self, state: BookState, expected_generation: int) -> bool:
        token = self.token_provider()
        _body, generation = _download(self.bucket, "book/state.json", token)
        if generation != expected_generation:
            return False
        return _upload(
            self.bucket,
            "book/state.json",
            _dump(state).encode("utf-8"),
            token,
            if_generation_match=expected_generation,
        )

    def try_lock(self, owner: str, now: datetime, ttl_s: int = 50) -> bool:
        token = self.token_provider()
        body, generation = _download(self.bucket, "book/lock", token)
        moment = as_utc(now)
        if body:
            current = json.loads(body.decode("utf-8"))
            expires = as_utc(datetime.fromisoformat(current["expires"].replace("Z", "+00:00")))
            if current["owner"] != owner and expires > moment:
                return False
        match = 0 if generation is None else generation
        payload = json.dumps({"owner": owner, "expires": iso(moment + timedelta(seconds=ttl_s))}).encode("utf-8")
        return _upload(self.bucket, "book/lock", payload, token, if_generation_match=match)

    def unlock(self, owner: str) -> None:
        token = self.token_provider()
        body, generation = _download(self.bucket, "book/lock", token)
        if not body or generation is None:
            return
        current = json.loads(body.decode("utf-8"))
        if current.get("owner") == owner:
            _delete(self.bucket, "book/lock", token, generation)


def _dump(state: BookState) -> str:
    return json.dumps({"state": json.loads(state.model_dump_json())}, sort_keys=True)


class GcsBudgetBook:
    def __init__(self, bucket: str, token_provider=None) -> None:
        self.bucket = bucket
        self.key = "budget/tokens.json"
        self.token_provider = token_provider or metadata_token

    def tokens(self, month: str) -> int:
        token = self.token_provider()
        body, _generation = _download(self.bucket, self.key, token)
        if not body:
            return 0
        return int(json.loads(body.decode("utf-8")).get(month, 0))

    def add(self, month: str, amount: int, day: str | None = None) -> None:
        token = self.token_provider()
        body, generation = _download(self.bucket, self.key, token)
        data = json.loads(body.decode("utf-8")) if body else {}
        data[month] = int(data.get(month, 0)) + int(amount)
        if day:
            data[day] = int(data.get(day, 0)) + int(amount)
        match = 0 if generation is None else generation
        _upload(self.bucket, self.key, json.dumps(data).encode("utf-8"), token, if_generation_match=match)


def cycle_log_key(cycle_id: str) -> str | None:
    """logs/dt=AAAA-MM-DD/{cycle_id}.jsonl si el id trae fecha UTC."""
    import re

    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T\d{6}Z.*", cycle_id)
    if not match:
        return None
    day = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return f"logs/dt={day}/{cycle_id}.jsonl"


def _log_key(event: dict) -> str:
    occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    day = as_utc(occurred).strftime("%Y-%m-%d")
    return f"logs/dt={day}/{event['correlation_id']}.jsonl"


def _parse_jsonl(body: bytes) -> list[dict]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def _days_between(start: datetime, end: datetime) -> list[str]:
    day = as_utc(start).date()
    last = as_utc(end).date()
    found = []
    while day <= last:
        found.append(day.isoformat())
        day += timedelta(days=1)
    return found


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _download(bucket: str, key: str, token: str) -> tuple[bytes | None, int | None]:
    import urllib.error
    import urllib.request

    meta_url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{key.replace('/', '%2F')}"
    req = urllib.request.Request(meta_url, headers=_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            meta = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise
    generation = int(meta["generation"])
    media = urllib.request.Request(meta_url + "?alt=media", headers=_headers(token))
    with urllib.request.urlopen(media, timeout=10) as response:
        return response.read(), generation


def _upload(bucket: str, key: str, body: bytes, token: str, content_type: str = "application/json", if_generation_match: int | None = None) -> bool:
    import urllib.error
    import urllib.request

    query = f"uploadType=media&name={key.replace('/', '%2F')}"
    if if_generation_match is not None:
        query += f"&ifGenerationMatch={if_generation_match}"
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?{query}"
    headers = _headers(token)
    headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status in (200, 201)
    except urllib.error.HTTPError as exc:
        if exc.code == 412:
            return False
        raise


def _delete(bucket: str, key: str, token: str, generation: int) -> None:
    import urllib.request

    url = (
        f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{key.replace('/', '%2F')}"
        f"?ifGenerationMatch={generation}"
    )
    req = urllib.request.Request(url, headers=_headers(token), method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        return


def _list(bucket: str, prefix: str, token: str) -> list[str]:
    import urllib.parse
    import urllib.request

    names: list[str] = []
    page = ""
    while True:
        query = urllib.parse.urlencode({"prefix": prefix, "maxResults": "1000", **({"pageToken": page} if page else {})})
        url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o?{query}"
        req = urllib.request.Request(url, headers=_headers(token))
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        names.extend(item["name"] for item in payload.get("items") or [])
        page = str(payload.get("nextPageToken") or "")
        if not page or len(names) >= 5000:
            break
    return names


def _download_many(bucket: str, names: list[str], token: str) -> list[bytes | None]:
    if not names:
        return []
    from concurrent.futures import ThreadPoolExecutor

    workers = min(8, len(names))

    def one(name: str) -> bytes | None:
        body, _gen = _download(bucket, name, token)
        return body

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, names))


_ = timezone
