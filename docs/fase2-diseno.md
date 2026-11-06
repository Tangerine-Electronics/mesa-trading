# Fase 2 — solo diseño

No hay código de acciones ni de ETFs en este build. Hace falta un OK nuevo de Pedro para construirlo.

## Qué se reutilizaría

La misma interfaz `MarketConnector` (`candles`, `order_book`, `trades`, `funding`, `market_status`, `metadata`). Un conector nuevo leería un CSV o una API de datos, sin llave de broker. El núcleo (`state`, `policy`, `risk`, `SimBroker`, `book`, `logs`) no cambia de forma.

## Qué cambiaría

- Horario: la mesa no opera cuando el mercado de ese símbolo está cerrado. El filtro de hechos duros ya tiene el motivo `mercado_cerrado`.
- Velas diarias u horarias, no de 5 minutos, para un portafolio de retiro.
- House no encaja bien con ETFs de retiro: se propone no usarlo en Fase 2.
- Spy, si algún día se enciende aquí, copiaría movimientos públicos y atrasados (13F y Form 4), con veto si el dato es viejo. No hay conector de eso en este repo.
- El perfil de riesgo de retiro lo define Pedro antes de construir. Esta mesa no es asesoría.

## Universo

Pendiente con Pedro: qué ETFs y si el acceso es vía el SIC. Hasta entonces el archivo de configuración no tiene mercados de acciones.
