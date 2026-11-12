# Fuentes de datos (F1)

Verificado el 2026-11-06, antes de dejar los conectores prendidos. La mesa solo hace lecturas públicas, sin credenciales, por el cliente con lista blanca. No se llama a ningún endpoint de órdenes.

## Coinbase Exchange — apagado

- Documentación: https://docs.cdp.coinbase.com/exchange/introduction/welcome y https://docs.cdp.coinbase.com/exchange/rest-api/rate-limits
- La página de bienvenida dice que acceder a la Exchange Market Data API obliga a aceptar los [Market Data Terms of Use](https://www.coinbase.com/legal/market_data).
- Límite de la API pública (no es el motivo del apagado): 10 solicitudes por segundo por IP, ráfagas hasta 15.
- Cláusula que impide el uso, sección 3 («Restrictions and Responsibilities»), leída el 2026-11-01. Sin consentimiento previo y por escrito de Coinbase no se puede:

  > Use any Market Data to, or permit or authorize any third party to, in whole or in part, develop, train, fine-tune, teach, validate, benchmark, or otherwise improve any artificial intelligence or machine learning model, algorithm, chatbot, agent, or other automated system, whether generative or non-generative, or for any other purpose related to the research, development, or operation of artificial intelligence technologies.

- La mesa entrega el estado del mercado a Jev y mide si esas probabilidades aciertan. Eso cae en validar un modelo y en operar un sistema automatizado con ese dato.
- Conector: **apagado** (`connectors.coinbase.enabled=false`). El esquema rechaza encenderlo. El host no está en la lista blanca HTTP. BTC y ETH salen de Hyperliquid (`POST /info`); el pool DEX, de GeckoTerminal.
- Encenderlo exige consentimiento escrito de Coinbase y un PR.

## GeckoTerminal (datos DEX de CoinGecko)

- Página del producto: https://www.geckoterminal.com/dex-api
- Host permitido: `api.geckoterminal.com`, solo `GET /api/v2/...`
- Límite vigente en esa página (2026-11-06): el plan público es de **10 llamadas por minuto**. El plan de pago sube a 250 por minuto. La spec estimaba ~30; hoy el público es 10. House lee un solo pool (velas + reserva) una vez por ciclo, sin ráfaga de reintentos. No se agregan más pools DEX mientras el plan público siga en 10/min.
- Términos de la API de CoinGecko (versión del 5 de septiembre de 2025, https://www.coingecko.com/en/api_terms): hay licencia para integrar la API en una aplicación; se puede cobrar por el producto propio; no se puede revender el acceso a la API. Piden la atribución «Powered by CoinGecko». La propia guía de usos incluye bots de trading y backtesting. El caché, si se guarda, debe refrescarse al menos cada 24 horas: aquí el dato se vuelve a leer cada ciclo. La bitácora guarda el snapshot numérico de la mesa (90 días), no una copia para reventa.
- La cláusula que prohíbe usar la API para promover apuestas no aplica: esto es una simulación privada de una mesa, no un producto de apuestas.
- Conector: **encendido**. Pool de referencia: WETH/USDC 0.05% en Ethereum (`0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`), leído sin llave el 2026-11-06 (HTTP 200, reserva publicada por ellos).
- Atribución en el resumen diario y en `/reportes`.

## Hyperliquid, info API

- Documentación: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api y la página de rate limits.
- Host permitido: `api.hyperliquid.xyz`, solo `POST /info`. `POST /exchange` está fuera de la lista blanca y el test A4 lo rechaza antes de abrir la red.
- Límite publicado por IP: 1200 de peso por minuto. `l2Book` pesa 2; el resto de `info` documentado pesa 20, con peso extra en `candleSnapshot` según cuántas velas vuelvan. Los límites por dirección aplican a acciones de trading, no a `info`.
- Staging lee cinco perps (BTC, ETH, SOL, DOGE, XRP). `metaAndAssetCtxs` se cachea en el proceso del ciclo, así que el funding no se pide una vez por mercado. El peso de un ciclo queda muy por debajo de 1200 por minuto.
- La documentación presenta esta API como API pública para desarrolladores. La mesa no usa el SDK (está en la lista negra de dependencias) ni firma nada.
- Conector: **encendido**. Prueba sin credenciales: `POST /info` con `{"type":"meta"}` respondió 200.
- Mercados: BTC perpetuo, para funding y para el único caso en que «corto» existe dentro de la simulación. En spot, corto sigue siendo no entrar.

## Spy y Fase 2

- Billeteras y banderas de contrato: no hay conector. `bots.spy.enabled=false`.
- Acciones, ETFs, EDGAR y SIC: no se construyen en este build. Quedan descritos en `docs/fase2-diseno.md`.
