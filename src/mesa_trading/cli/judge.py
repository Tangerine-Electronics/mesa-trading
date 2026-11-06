"""Sirve el juez. Si el modelo no está fijado, el proceso no arranca."""

from __future__ import annotations

import os

import uvicorn

from mesa_trading.config import default_desk_path, load_desk


def main() -> int:
    load_desk(default_desk_path())
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("mesa_trading.judge_service.app:app", host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
