"""Arma el resumen diario y la calibración. No cambia el modo de ningún bot."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mesa_trading.book.store import equity_usd, note_drawdown
from mesa_trading.cli.stores import open_book, open_logs
from mesa_trading.config import default_desk_path, default_promotion_path, load_desk, load_promotion
from mesa_trading.reports.build import apply_verdict, build_calibration, build_daily, write_reports
from mesa_trading.storage import LocalRoot, data_root_from_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mesa-report")
    parser.add_argument("--config", default=str(default_desk_path()))
    parser.add_argument("--promotion", default=str(default_promotion_path()))
    parser.add_argument("--data-dir", default=os.environ.get("MESA_DATA_DIR", "/tmp/mesa-trading"))
    args = parser.parse_args(argv)
    try:
        config = load_desk(Path(args.config))
        promo = load_promotion(Path(args.promotion))
    except Exception as exc:
        print(f"configuracion invalida: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    logs = open_logs(args.data_dir)
    book_store = open_book(args.data_dir, config.capital_usd, now)
    state, _gen = book_store.read()
    mark = None
    if state.position is not None:
        raw = state.last_prices.get(state.position.market)
        mark = None if raw is None else __import__("decimal").Decimal(raw)
    equity = equity_usd(state, mark)
    drawdown = note_drawdown(state, equity)
    # Dos días de bitácora, no el bucket entero. El tick ya no depende de este barrido.
    events = logs.events_between(now - timedelta(days=1, hours=2), now)
    book_view = {"realized_pnl_usd": format(state.realized_pnl_usd, "f"), "drawdown_usd": format(drawdown, "f")}
    daily = build_daily(events, config, now, book=book_view)
    prior = _load_pairs(args.data_dir)
    calibration = build_calibration(events, promo, config, now, pair_store=prior)
    apply_verdict(
        daily,
        calibration,
        promo,
        closed_trades=int(state.closed_trades),
        started_at=state.started_at,
        capital_usd=config.capital_usd,
        max_drawdown_usd=drawdown,
        now=now,
    )
    _save_pairs(args.data_dir, calibration.get("pair_store") or {})
    if os.environ.get("MESA_BUCKET"):
        root = data_root_from_env()
        _write_remote(root, daily, calibration)
    else:
        write_reports(Path(args.data_dir), daily, calibration)
    return 0


def _load_pairs(data_dir: str) -> dict | None:
    import json

    if os.environ.get("MESA_BUCKET"):
        text = data_root_from_env().read_text("reportes/calibracion/pares.json")
        return json.loads(text) if text else None
    path = Path(data_dir) / "reportes" / "calibracion" / "pares.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_pairs(data_dir: str, store: dict) -> None:
    import json

    payload = json.dumps(store, ensure_ascii=False)
    if os.environ.get("MESA_BUCKET"):
        data_root_from_env().write_text("reportes/calibracion/pares.json", payload)
        return
    path = Path(data_dir) / "reportes" / "calibracion"
    path.mkdir(parents=True, exist_ok=True)
    (path / "pares.json").write_text(payload, encoding="utf-8")


def _write_remote(root, daily, calibration) -> None:
    import json
    from mesa_trading.reports.build import render_calibration_md, render_daily_md

    calibration = {key: value for key, value in calibration.items() if key != "pair_store"}
    fecha = daily["fecha"]
    root.write_text(f"reportes/diario/{fecha}.json", json.dumps(daily, ensure_ascii=False, indent=2))
    root.write_text(f"reportes/diario/{fecha}.md", render_daily_md(daily))
    root.write_text(f"reportes/calibracion/{fecha}.json", json.dumps(calibration, ensure_ascii=False, indent=2))
    root.write_text(f"reportes/calibracion/{fecha}.md", render_calibration_md(calibration))
    root.write_text(f"reportes/calibracion/agregados/{fecha}.json", json.dumps(calibration["agregados"], ensure_ascii=False, indent=2))
    index = {
        "fecha": fecha,
        "generado_en": daily["generado_en"],
        "diario": {"md": f"reportes/diario/{fecha}.md", "json": f"reportes/diario/{fecha}.json"},
        "calibracion": {"md": f"reportes/calibracion/{fecha}.md", "json": f"reportes/calibracion/{fecha}.json"},
        "alertas": daily["alertas"],
    }
    root.write_text("reportes/ultimo.json", json.dumps(index, ensure_ascii=False, indent=2))
    _ = LocalRoot


if __name__ == "__main__":
    raise SystemExit(main())
