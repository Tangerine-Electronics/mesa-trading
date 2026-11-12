# mesa-trading

Mesa de trading 24/7 con **dinero simulado**. No hay broker real, ni llaves de exchange, ni llaves privadas.

**Gambler** y **House** corren en **simulado**: `SimBroker` abre y cierra una sola posición con dinero ficticio, después de comisiones y slippage. **Spy** está apagado (`bots.spy.enabled=false`) y en sombra. No hay modo real. El reporte recomienda un veredicto; no cambia el modo.

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

La configuración está en `config/desk.yaml` y `config/promotion.yaml`. Las fuentes y sus límites están en `docs/fuentes.md`.

## Carga de staging y veredicto

Universo: BTC, ETH, SOL, DOGE y XRP perp en Hyperliquid, más el pool WETH/USDC en GeckoTerminal. Coinbase sigue apagado.

Filtros en `filters` (los libros reales quedan muy por debajo):

| Parámetro | Valor | Por qué |
| --- | --- | --- |
| `max_spread_bps` | 25 | BTC en Hyperliquid ~0.1 bp; el pool sintético ~10 bp. 25 deja pasar ambos y corta un libro roto. |
| `min_liquidity_usd` | 10000 | Esos libros andan en cientos de millones. 10000 solo tira polvo. |
| `max_vol` | 0.05 | La vol realizada de 5 min anda en ~0.002. 0.05 es un libro disparado. |
| `max_fee_fraction` | 0.02 | La comisión mínima no puede comerse más del 2% del tamaño. |

`/estado` lee solo `book/state.json` (el ciclo anota ahí `last_cycle_id`). No lista la bitácora.

El resumen diario trae el embudo (vistos → en banca → rechazados por paso y por motivo → juez → decisiones → operaciones simuladas), el gasto real de Jev y un techo estimado.

Tope de Jev: **0.15 USD/día** y **5 USD/mes**. Techo si los 6 mercados llegan al juez en cada ciclo de 5 min, a 800 tokens de entrada (un snapshot real de BTC midió ~450): **~0.06 USD/día**, ~1.80 USD/mes. Si el prompt real es más caro, el tope diario corta antes.

Veredicto (`veredicto.estado`), solo con dinero simulado:

- **insuficiente** hasta 200 cierres y 14 días.
- **go_tentativo** si, con esa muestra, el PnL después de comisiones y slippage es > 0 y el skill de Brier de las preguntas de política es ≥ 0.02. No autoriza dinero real.
- **no_go** si, ya con la muestra, el PnL no es positivo o el skill es ≤ 0. También si el drawdown pasa el 15% del capital antes.
- Con una sola posición, ~10 cierres al día juntan la muestra en ~20 días; ~2 al día, en ~100. El reporte calcula el ritmo observado.

## Staging

Proyecto `tangerine-staging-510423`, región `northamerica-south1`. El despliegue es `scripts/staging-apply.sh` con Workload Identity (cuenta `sa-forge-staging`), sin llaves JSON. Terraform no carga el valor de `mesa-trading-jev-key`: si el secreto está vacío, `/health` del juez responde `"jev_key": "missing"` y la mesa hace hold.
