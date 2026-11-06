"""A3. Falla si el árbol importa SDKs de exchanges o símbolos de dinero real."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_PARTS = {"tests/safety", ".venv", ".git"}
IMPORTS = (
    "ccxt",
    "python-binance",
    "coinbase-advanced-py",
    "alpaca",
    "ib_insync",
    "hyperliquid-python-sdk",
    "web3",
    "eth_account",
    "solders",
    "solana",
    "bitcoinlib",
)
SYMBOLS = ("withdraw", "private_key", "sign_transaction", "api_secret")


def _files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".py", ".toml", ".txt", ".in"}:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(part in rel for part in SKIP_PARTS):
            continue
        yield rel, path.read_text(encoding="utf-8", errors="ignore")


def test_a3_no_forbidden_imports_or_symbols():
    offenders = []
    for rel, text in _files():
        lowered = text.lower()
        for name in IMPORTS:
            if f"import {name}" in lowered or f"from {name}" in lowered or f'"{name}"' in lowered:
                offenders.append((rel, name))
        if rel.endswith("pyproject.toml"):
            for name in IMPORTS:
                if name in lowered:
                    offenders.append((rel, name))
        for symbol in SYMBOLS:
            if symbol in lowered:
                offenders.append((rel, symbol))
    assert offenders == []
