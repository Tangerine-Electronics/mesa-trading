"""Sirve la API de solo lectura."""

from __future__ import annotations

import os
import sys

import uvicorn


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    # Esta línea sale antes de importar la app. Si Cloud Run mata la revisión
    # sin logs, al menos se ve que el proceso arrancó y en qué puerto.
    print(f"mesa-trading-api en 0.0.0.0:{port}", file=sys.stderr, flush=True)
    # Uvicorn no abre el socket hasta terminar el lifespan
    # (uvicorn/server.py: Server.startup). Esta API no tiene hook de arranque;
    # apagarlo hace que /health exista en cuanto el proceso entra al serve.
    uvicorn.run(
        "mesa_trading.api.app:app",
        host="0.0.0.0",
        port=port,
        lifespan="off",
        access_log=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
