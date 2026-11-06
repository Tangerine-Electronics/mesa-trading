# mesa-trading

Mesa de trading 24/7 con **dinero simulado**. No hay broker real, ni llaves de exchange, ni llaves privadas.

Los bots **Gambler** y **House** arrancan en **modo sombra**: deciden y lo anotan, sin crear órdenes. **Spy** está apagado (`bots.spy.enabled=false`). Pasar un bot a simulado lo hace un PR con OK de Pedro; el reporte solo recomienda.

## Cómo se mueve un ciclo

1. El reloj dispara el job `mesa-trading-tick` cada 5 minutos.
2. `state/` arma una foto chica del mercado (sin ver el futuro).
3. `filter/` tira lo que no vale la pena.
4. `mesa-trading-judge` pregunta a Jev `jev-1.14.0` (una llamada por batería). Si no hay llave, si se vence el tiempo o si se pasa el tope de US$5 al mes, la mesa hace hold.
5. `policy/` aplica umbrales. `risk/` puede vetar. Nada de eso lo salta el modelo.
6. En sombra no hay orden. En simulado, `SimBroker` es la única implementación de `Broker`.
7. Todo queda en la bitácora. A las 07:00 hora de la Ciudad de México, `mesa-trading-report` publica el resumen y la calibración.

## API de solo lectura

- `GET /health` → 200, `"broker": "simulado"`
- `GET /estado`
- `GET /reportes`
- `GET /reportes/ultimo.json`
- `GET /reportes/diario/{fecha}.json`
- `GET /reportes/calibracion/{fecha}.json`

## Desarrollo

```bash
pip install -e ".[dev]"
pytest
```

La configuración que fijó Pedro está en `config/desk.yaml` y `config/promotion.yaml`. Las fuentes y sus límites están en `docs/fuentes.md`.

## Staging

Proyecto `tangerine-staging-510423`, región `northamerica-south1`. El despliegue es `scripts/staging-apply.sh` con Workload Identity (cuenta `sa-forge-staging`), sin llaves JSON. Terraform no carga el valor de `mesa-trading-jev-key`: si el secreto está vacío, `/health` del juez responde `"jev_key": "missing"` y la mesa hace hold.
