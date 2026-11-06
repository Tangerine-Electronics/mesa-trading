"""Arma el resumen diario y la calibración. No cambia el modo de ningún bot."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mesa_trading.book.store import equity_usd
from mesa_trading.cli.stores import open_book, open_logs
from mesa_trading.config import default_desk_path, default_promotion_path, load_desk, load_promotion
from mesa_trading.reports.build import build_calibration, build_daily, write_reports
from mesa_trading.storage import LocalRoot, data_root_from_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mesa-report")
    parser.add_argument("--config", default=os.environ.get("MESA_DESK_CONFIG", str(default_desk_path())))
    parser.add_argument("--promotion", default=os.environ.get("MESA_PROMOTION_CONFIG", str(default_promotion_path())))
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
    drawdown = state.peak_equity_usd - equity
    if drawdown < 0:
        drawdown = 0
    events = logs.all_events()
    daily = build_daily(
        events,
        config,
        now,
        book={"realized_pnl_usd": format(state.realized_pnl_usd, "f"), "drawdown_usd": format(drawdown, "f")},
    )
    calibration = build_calibration(events, promo, config, now)
    if os.environ.get("MESA_BUCKET"):
        root = data_root_from_env()
        _write_remote(root, daily, calibration)
    else:
        write_reports(Path(args.data_dir), daily, calibration)
    return 0


def _write_remote(root, daily, calibration) -> None:
    import json
    from mesa_trading.reports.build import render_calibration_md, render_daily_md

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
