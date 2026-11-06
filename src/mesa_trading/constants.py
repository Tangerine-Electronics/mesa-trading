"""Topes y versión fijados en código. Subirlos exige un PR con OK de Pedro."""

from __future__ import annotations

from decimal import Decimal

PINNED_MODEL = "jev-1.14.0"
ALLOWED_MODELS = frozenset({PINNED_MODEL})
MONTHLY_BUDGET_USD = Decimal("5")
USD_PER_MILLION_INPUT_TOKENS = Decimal("0.042")
TOKEN_BUDGET = 400
SCHEMA_VERSION = "1"
MODES = frozenset({"shadow", "simulated"})

# 5 / 0.042 * 1_000_000 ≈ 119_047_619 tokens de entrada.
INPUT_TOKEN_CAP = int((MONTHLY_BUDGET_USD / USD_PER_MILLION_INPUT_TOKENS) * Decimal(1_000_000))
