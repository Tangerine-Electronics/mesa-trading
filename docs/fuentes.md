# Fuentes de datos (F1)

Verificado el 2026-11-06, antes de dejar los conectores prendidos. La mesa solo hace lecturas públicas, sin credenciales, por el cliente con lista blanca. No se llama a ningún endpoint de órdenes.

## Coinbase Exchange, API pública de mercado

- Documentación: https://docs.cdp.coinbase.com/exchange/introduction/welcome y https://docs.cdp.coinbase.com/exchange/rest-api/rate-limits
- Host permitido: `api.exchange.coinbase.com`, solo `GET /products/...` (velas, libro, trades). Quedan fuera cuentas, órdenes y transferencias.
- Límite publicado para endpoints públicos: 10 solicitudes por segundo por IP, con ráfagas de hasta 15. Un ciclo de la mesa hace unas pocas lecturas cada 5 minutos.
- Términos: la documentación dice que usar la API pública de mercado obliga a aceptar los Market Data Terms of Use. El 2026-11-06 la página legal (`coinbase.com/legal/market_data`) respondió con un reto de Cloudflare y no se pudo leer el texto completo. Lo que sí está publicado es que esos endpoints son de datos de mercado, sin llave. La mesa los usa para una simulación interna, no revende el feed.
- Conector: **encendido** (`connectors.coinbase.enabled=true`).
- Prueba en vivo, sin credenciales: `GET /products/BTC-USD/candles?granularity=300` respondió 200.

## GeckoTerminal (datos DEX de CoinGecko)

- Página del producto: https://www.geckoterminal.com/dex-api
- Host permitido: `api.geckoterminal.com`, solo `GET /api/v2/...`
- Límite vigente en esa página (2026-11-06): el plan público es de **10 llamadas por minuto**. El plan de pago sube a 250 por minuto. La spec estimaba ~30; hoy el público es 10. La mesa hace 1 o 2 lecturas cada 5 minutos (cerca de 0.4 por minuto) y el cliente no reintenta en ráfaga.
- Términos de la API de CoinGecko (versión del 5 de septiembre de 2025, https://www.coingecko.com/en/api_terms): hay licencia para integrar la API en una aplicación; se puede cobrar por el producto propio; no se puede revender el acceso a la API. Piden la atribución «Powered by CoinGecko». La propia guía de usos incluye bots de trading y backtesting. El caché, si se guarda, debe refrescarse al menos cada 24 horas: aquí el dato se vuelve a leer cada ciclo. La bitácora guarda el snapshot numérico de la mesa (90 días), no una copia para reventa.
- La cláusula que prohíbe usar la API para promover apuestas no aplica: esto es una simulación privada de una mesa, no un producto de apuestas.
- Conector: **encendido**. Pool de referencia: WETH/USDC 0.05% en Ethereum (`0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`), leído sin llave el 2026-11-06 (HTTP 200, reserva publicada por ellos).
- Atribución en el resumen diario y en `/reportes`.

## Hyperliquid, info API

- Documentación: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api y la página de rate limits.
- Host permitido: `api.hyperliquid.xyz`, solo `POST /info`. `POST /exchange` está fuera de la lista blanca y el test A4 lo rechaza antes de abrir la red.
- Límite publicado por IP: 1200 de peso por minuto. `l2Book` pesa 2; el resto de `info` documentado pesa 20, con peso extra en `candleSnapshot` según cuántas velas vuelvan. Los límites por dirección aplican a acciones de trading, no a `info`.
- La documentación presenta esta API como API pública para desarrolladores. La mesa no usa el SDK (está en la lista negra de dependencias) ni firma nada.
- Conector: **encendido**. Prueba sin credenciales: `POST /info` con `{"type":"meta"}` respondió 200.
- Mercados: BTC perpetuo, para funding y para el único caso en que «corto» existe dentro de la simulación. En spot, corto sigue siendo no entrar.

## Spy y Fase 2

- Billeteras y banderas de contrato: no hay conector. `bots.spy.enabled=false`.
- Acciones, ETFs, EDGAR y SIC: no se construyen en este build. Quedan descritos en `docs/fase2-diseno.md`.
