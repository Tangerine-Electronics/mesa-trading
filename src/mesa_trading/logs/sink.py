"""Bitácora JSONL. Un objeto por ciclo. Repetir un event_id no duplica el renglón."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from mesa_trading.util import as_utc


class LogSink:
    def append(self, event: dict) -> bool:
        raise NotImplementedError

    def cycle_finished(self, cycle_id: str) -> bool:
        raise NotImplementedError

    def read_cycle(self, cycle_id: str) -> list[dict]:
        raise NotImplementedError

    def all_events(self) -> list[dict]:
        raise NotImplementedError

    def events_between(self, start: datetime, end: datetime) -> list[dict]:
        begin = as_utc(start)
        finish = as_utc(end)
        rows = []
        for event in self.all_events():
            when = as_utc(datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")))
            if begin <= when <= finish:
                rows.append(event)
        return rows

    def flush(self) -> None:
        """Cierra la bitácora. El disco ya escribió; GCS junta el ciclo y sube una vez."""
        return None


class FileLogSink(LogSink):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict) -> bool:
        path = self._path(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_file(path)
        if any(row.get("event_id") == event["event_id"] for row in existing):
            return False
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")
        return True

    def cycle_finished(self, cycle_id: str) -> bool:
        return any(
            row["event_type"] == "CycleFinished" and row["correlation_id"] == cycle_id
            for row in self.read_cycle(cycle_id)
        )

    def read_cycle(self, cycle_id: str) -> list[dict]:
        matches = list(self.root.glob(f"dt=*/{cycle_id}.jsonl")) + list(self.root.glob(f"dt=*/{cycle_id}.ndjson"))
        if not matches:
            return []
        return self._read_file(matches[0])

    def all_events(self) -> list[dict]:
        rows: list[dict] = []
        paths = sorted(self.root.glob("dt=*/*.jsonl")) + sorted(self.root.glob("dt=*/*.ndjson"))
        for path in paths:
            rows.extend(self._read_file(path))
        return rows

    def events_between(self, start: datetime, end: datetime) -> list[dict]:
        begin = as_utc(start)
        finish = as_utc(end)
        rows: list[dict] = []
        day = begin.date()
        while day <= finish.date():
            folder = self.root / f"dt={day.isoformat()}"
            if folder.exists():
                paths = sorted(folder.glob("*.jsonl")) + sorted(folder.glob("*.ndjson"))
                for path in paths:
                    for row in self._read_file(path):
                        when = as_utc(datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00")))
                        if begin <= when <= finish:
                            rows.append(row)
            day += timedelta(days=1)
        return rows

    def _path(self, event: dict) -> Path:
        occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        day = as_utc(occurred).strftime("%Y-%m-%d")
        return self.root / f"dt={day}" / f"{event['correlation_id']}.jsonl"

    @staticmethod
    def _read_file(path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
