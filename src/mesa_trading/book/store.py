"""Una posición para toda la mesa. Escritura con precondición de generación y candado."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from mesa_trading.models import BookState, Position
from mesa_trading.util import as_utc, iso


def fresh_book(capital: Decimal, now: datetime) -> BookState:
    day = as_utc(now).strftime("%Y-%m-%d")
    return BookState(
        cash_usd=capital,
        day_start_equity_usd=capital,
        day_start_utc=day,
        peak_equity_usd=capital,
        equity_hwm_usd=capital,
    )


def note_drawdown(book: BookState, equity: Decimal) -> Decimal:
    """Sube el pico y guarda el peor pico-a-valle, no solo el hueco de ahora."""
    if equity > book.peak_equity_usd:
        book.peak_equity_usd = equity
    current = book.peak_equity_usd - equity
    if current < 0:
        current = Decimal("0")
    if current > book.max_drawdown_usd:
        book.max_drawdown_usd = current
    return book.max_drawdown_usd


def equity_usd(book: BookState, mark: Decimal | None = None) -> Decimal:
    if book.position is None:
        return book.cash_usd
    price = mark if mark is not None else book.position.entry_price
    if book.position.side == "long":
        return book.cash_usd + book.position.qty * price
    unrealized = (book.position.entry_price - price) * book.position.qty
    return book.cash_usd + book.position.notional_usd + unrealized


class BookStore:
    def read(self) -> tuple[BookState, int]:
        raise NotImplementedError

    def write(self, state: BookState, expected_generation: int) -> bool:
        raise NotImplementedError

    def try_lock(self, owner: str, now: datetime, ttl_s: int = 50) -> bool:
        raise NotImplementedError

    def unlock(self, owner: str) -> None:
        raise NotImplementedError


class FileBookStore(BookStore):
    def __init__(self, root: Path, capital: Decimal = Decimal("1000"), now: datetime | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._mu = threading.Lock()
        self._state_path = root / "state.json"
        self._lock_path = root / "lock"
        if not self._state_path.exists():
            initial = fresh_book(capital, now or datetime.now(timezone.utc))
            self._state_path.write_text(_dump(initial, 0), encoding="utf-8")

    def read(self) -> tuple[BookState, int]:
        payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        return BookState.model_validate(payload["state"]), int(payload["generation"])

    def write(self, state: BookState, expected_generation: int) -> bool:
        with self._mu:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            if int(payload["generation"]) != expected_generation:
                return False
            self._state_path.write_text(_dump(state, expected_generation + 1), encoding="utf-8")
            return True

    def try_lock(self, owner: str, now: datetime, ttl_s: int = 50) -> bool:
        with self._mu:
            current = self._read_lock()
            moment = as_utc(now)
            if current and current["owner"] != owner and as_utc(datetime.fromisoformat(current["expires"])) > moment:
                return False
            expires = moment + timedelta(seconds=ttl_s)
            self._lock_path.write_text(
                json.dumps({"owner": owner, "expires": iso(expires)}),
                encoding="utf-8",
            )
            return True

    def unlock(self, owner: str) -> None:
        with self._mu:
            current = self._read_lock()
            if current and current["owner"] == owner:
                self._lock_path.unlink(missing_ok=True)

    def _read_lock(self) -> dict | None:
        if not self._lock_path.exists():
            return None
        return json.loads(self._lock_path.read_text(encoding="utf-8"))


def mark_price(book: BookState, market: str) -> Decimal | None:
    raw = book.last_prices.get(market)
    if raw is None:
        if book.position and book.position.market == market:
            return book.position.entry_price
        return None
    return Decimal(raw)


def open_position(book: BookState, position: Position, fee: Decimal, slip: Decimal) -> BookState:
    book.position = position
    book.fees_usd += fee
    book.slippage_usd += slip
    book.cash_usd -= position.notional_usd + fee + slip
    return book


def close_position(book: BookState, exit_price: Decimal, fee: Decimal, slip: Decimal, when: datetime) -> Decimal:
    assert book.position is not None
    pos = book.position
    gross = (exit_price - pos.entry_price) * pos.qty if pos.side == "long" else (pos.entry_price - exit_price) * pos.qty
    pnl = gross - fee - slip - pos.fees_usd - pos.slippage_usd
    if pos.side == "long":
        book.cash_usd += pos.qty * exit_price - fee - slip
    else:
        book.cash_usd += pos.notional_usd + (pos.entry_price - exit_price) * pos.qty - fee - slip
    book.realized_pnl_usd += pnl
    book.day_realized_pnl_usd += pnl
    book.closed_trades += 1
    book.fees_usd += fee
    book.slippage_usd += slip
    book.position = None
    _ = when
    return pnl


def _dump(state: BookState, generation: int) -> str:
    return json.dumps(
        {"generation": generation, "state": json.loads(state.model_dump_json())},
        indent=2,
        sort_keys=True,
    )
