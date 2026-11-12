from decimal import Decimal

from mesa_trading.book.store import fresh_book, note_drawdown
from tests.helpers import T0


def test_max_drawdown_survives_a_recovery():
    book = fresh_book(Decimal("1000"), T0)
    assert note_drawdown(book, Decimal("1000")) == Decimal("0")
    assert note_drawdown(book, Decimal("800")) == Decimal("200")
    assert note_drawdown(book, Decimal("950")) == Decimal("200")
    assert book.peak_equity_usd == Decimal("1000")
    assert book.max_drawdown_usd == Decimal("200")
