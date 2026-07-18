# AlphaOS

Motor institucional de inteligencia financiera: señales, gestión de posiciones,
portafolio y aprendizaje continuo. Este repo contiene únicamente la
**arquitectura y el esqueleto** — la lógica de scoring/convicción y las
integraciones de datos reales se implementan módulo por módulo.

## Filosofía de construcción

No se construye todo de una vez. Orden recomendado:

1. **Señales** (`alpha_os/engine/signal_engine.py`, `conviction.py`) — scoring
   multi-factor por activo.
2. **Gestión de posiciones** (`alpha_os/positions/position_manager.py`) —
   ciclo de vida post-compra (Módulo 10 del spec original).
3. **Portafolio multi-activo** (`alpha_os/positions/portfolio_manager.py`) —
   exposición (por ticker/sector/país **y por clase de activo**: equity/
   crypto/fx/commodity/etf/bond, usando `OperationEntry.asset_class`),
   correlación cross-asset, riesgo sistémico. **Conectado**: correlación
   delegada a `CrossAssetCorrelationAdapter` en vez de duplicar esa lógica
   — la versión anterior tenía su propio bug de timezone (cripto en UTC vs.
   equities en la tz de su bolsa) nunca corregido aquí, que hacía que
   ningún par cripto↔equity se calculara (verificado: BTC-USD/AAPL daban 0
   pares incluso con umbral de correlación en 0). Riesgo sistémico
   (pendiente desde el diseño inicial) ahora conectado vía
   `MarketRegimeEngine`: marca alta concentración cripto durante eventos de
   volatilidad, y exposición larga alta en equities durante regímenes
   bajistas. Probado con un portafolio real mixto (AAPL + BTC-USD + ETH-USD):
   detectó correctamente 75% de concentración en cripto y la correlación
   real BTC-USD/ETH-USD (0.881).
4. **Aprendizaje continuo** (`alpha_os/positions/journal.py`,
   `alpha_os/engine/learning_engine.py`) — diario + post-mortem + reporte
   de desempeño por factor. **Conectado**: persistencia real en SQLite
   (`alpha_os/positions/storage.py`, `data/alphaos.db`) — antes vivía todo
   en memoria y se perdía al reiniciar el servidor, lo cual hacía
   imposible aprender de nada. Post-mortem y recalibración se derivan
   únicamente de posiciones cerradas con `original_signal` registrada, con
   una muestra mínima (10 ocurrencias) por factor antes de sugerir
   cualquier ajuste — nunca se aplica automáticamente a
   `DEFAULT_FACTOR_WEIGHTS`, solo se reporta para revisión humana (spec:
   "nunca sobreoptimizar"). `GET /positions/{id}/post-mortem`,
   `GET /learning/factor-performance`. Como el sistema es nuevo, hoy
   reporta honestamente "sin datos" — la primera vez que sea útil de
   verdad es tras acumular operaciones reales cerradas.

Cada capa se apoya en la anterior pero puede probarse de forma aislada.

## Estructura

```
alpha_os/
  core/           modelos de datos (Signal, InstitutionalAssessment, MarketRegimeAssessment, ...)
  adapters/       fuentes de datos intercambiables (mercado, fundamentales, noticias,
                  macro, institucional, on-chain/derivados/stablecoins)
  analysis/       indicadores técnicos, sentimiento, calendario macro (pendiente)
  engine/         conviction.py, signal_engine.py, institutional_engine.py,
                  market_regime_engine.py
  positions/      gestión de posiciones activas, portafolio, diario/aprendizaje
  api/            endpoints FastAPI
tests/            pytest — institucional, régimen de mercado, factores cripto
```

## Fuentes de datos

- **Mercado** (`adapters/market_data/yfinance_adapter.py`) y **fundamentales**
  (`adapters/fundamental/yfinance_adapter.py`): conectados, vía `yfinance`
  (gratis, sin API key).
- **Noticias/sentimiento** (`adapters/news/newsapi_adapter.py` +
  `analysis/sentiment.py`): conectado y probado con key real de NewsAPI
  (newsapi.org, plan gratis, solo uso local/desarrollo). Requiere
  `NEWSAPI_API_KEY` en `.env` — sin key configurada, se comporta como un mock
  (devuelve vacío). El sentimiento se calcula con un léxico simple de
  palabras positivas/negativas en inglés, no un modelo de NLP; las fuentes de
  nivel C (redes sociales/foros) se excluyen siempre del promedio. El adapter
  también filtra spam recurrente de despachos de abogados ("class action",
  "investor alert", etc.) que aparece para casi cualquier ticker todos los
  días y contaminaría el sentimiento. El factor `news_sentiment` es
  simétrico: suma si el sentimiento confirma la hipótesis direccional, resta
  si la contradice.
- **Macro** (`adapters/macro/fred_adapter.py`): conectado vía FRED (Federal
  Reserve Economic Data, gratis). Requiere `FRED_API_KEY` en `.env` — sin key
  configurada, se comporta como un mock. Trae CPI interanual (serie
  `CPIAUCSL`) y fed funds rate + tendencia de tasas (serie `FEDFUNDS`,
  comparando el valor actual contra el de ~6 meses atrás). El factor
  `macro_risk_controlled` es simétrico (no depende de la dirección de la
  hipótesis): CPI ≤3.5% suma, CPI ≥5% resta, zona intermedia no genera
  factor. El calendario de próximos eventos macro sigue sin fuente.
- **Institucional** (`alpha_os/engine/institutional_engine.py` +
  `adapters/institutional/`): conectado con 3 fuentes gratuitas — volumen
  relativo (proxy, del propio OHLCV), flujo de opciones (proxy, `yfinance`
  option chain: put/call ratio y actividad inusual vs. open interest en el
  vencimiento más próximo no-0DTE), y transacciones Form 4 de insiders vía
  SEC EDGAR (confirmado, sin API key — solo requiere un User-Agent
  identificable). Genera un `InstitutionalAssessment` con score -100..100,
  clasificación, confianza y `data_freshness`, siguiendo principios
  estrictos: el volumen nunca genera dirección por sí solo (solo confirma
  otras señales si ya existen), Form 4 descarta ejercicios de opciones (M),
  retención fiscal (F) y grants (A) — solo cuenta compra/venta discrecional
  en mercado abierto (P/S), con ventana de 90 días y decaimiento por
  repetición (evita que muchas ventas rutinarias de distintos insiders,
  extremadamente comunes y poco informativas, se acumulen linealmente hasta
  un extremo artificial). Distribución/acumulación **fuerte** (score ≤-70 o
  ≥70 en la dirección de la hipótesis) **bloquea la señal por completo**
  (veto, no solo resta puntos); moderada solo se suma/resta como un factor
  más.

  **Form 13F-HR** (`adapters/institutional/form13f_adapter.py`): conectado,
  vía SEC EDGAR, cobertura deliberadamente limitada a un puñado de gestores
  activos y discrecionales conocidos (Berkshire Hathaway, Renaissance
  Technologies, Bridgewater, Tiger Global — no indexadores como
  Vanguard/BlackRock, que replican el mercado y no reflejan convicción). No
  es un índice completo de los ~5000 filers trimestrales: eso requeriría
  agregar miles de filings por trimestre, fuera de alcance para "básico". El
  emparejamiento ticker→holding es por nombre de emisor normalizado (13F
  reporta por CUSIP, no por ticker), verificado con datos reales (Berkshire
  mantiene su posición en AAPL sin cambios, Renaissance abrió posición
  nueva, Bridgewater incrementó ~95% — todo consistente con lo público).
  Siempre `is_quarterly=True`: nunca se trata como posicionamiento en tiempo
  real, sin importar qué tan reciente sea el filing (multiplicador fijo
  0.15). Solo se compara cuando hay dato confirmado de ambos trimestres
  consultados — con uno solo no se infiere "posición nueva".

  13D/13G, operaciones en bloque, dark pool y flujos de ETF quedan
  pendientes — requieren proveedores de pago o agregación que excede el
  alcance "básico".
- **Cripto — Derivados** (`adapters/onchain/binance_derivatives_adapter.py`):
  conectado vía Binance Futures API pública (gratis, sin key). Funding rate,
  open interest y long/short ratio del vencimiento perpetuo. El factor
  `derivatives_leverage_risk` es **contrarian, no confirmatorio**: apalancamiento
  extremo en la dirección de la hipótesis se trata como riesgo de squeeze
  (mismo espíritu que `rsi_overextended`), nunca como señal a favor.
- **Cripto — Stablecoins** (`adapters/onchain/coingecko_stablecoin_adapter.py`):
  conectado vía CoinGecko (gratis, sin key, rate-limited). Supply circulante,
  dominancia y cambio 24h/7d — sin mint/burn directo en el tier gratis, se usa
  el cambio de market cap como proxy de cambio de supply (documentado en el
  modelo). El factor `stablecoin_liquidity` es deliberadamente débil y solo
  aporta "más liquidez disponible", nunca "van a comprar" (spec: "no asumir
  causalidad automática").
- **Cripto — On-chain profundo (Bitcoin)**
  (`adapters/onchain/blockchain_info_adapter.py`,
  `adapters/onchain/defillama_adapter.py`,
  `analysis/crypto_calendar.py`): conectado, vía blockchain.info y
  DeFiLlama, ambos gratis y sin API key.
  - **Wallet flow** (`GET /onchain/wallet-flow`): flujo real con historial
    diario (no solo snapshot), calculado a partir del propio historial de
    transacciones de la dirección — sin necesitar una base de datos propia.
    Detecta anomalías (desviación >2σ del promedio de los días previos,
    incluyendo el caso borde de un baseline perfectamente plano) y
    transacciones grandes con **umbral dinámico** vía mediana + MAD (robusto
    a que el propio outlier infle su umbral, un bug real que apareció y se
    corrigió durante las pruebas). **La identidad de la wallet (label,
    fuente, confianza) siempre la declara quien hace la consulta — este
    sistema nunca asume ni inventa que una dirección pertenece a un
    exchange/fondo/etc.**, tal como exige el spec. Cobertura acotada a
    ~150-200 transacciones recientes por consulta (wallets muy activas
    pueden no cubrir todo el `lookback_days` pedido; `effective_lookback_days`
    lo refleja honestamente).
  - **Network health** (`GET /onchain/network-health`): hashrate, conteo de
    transacciones y fee promedio (BTC), con cambio a 30 días.
  - **DeFi TVL** (`GET /onchain/defi-tvl`): TVL por chain vía DeFiLlama.
- **DeFi Intelligence** (`adapters/onchain/defillama_adapter.py`, DeFiLlama,
  gratis, sin key): completa lo que faltaba de TVL por chain.
  - **TVL por protocolo** (`GET /defi/protocol-tvl`): un protocolo
    específico (ej. `aave-v3`, `uniswap-v3`), no una chain completa.
  - **Volumen de DEXs** (`GET /defi/dex-volume`): volumen agregado 24h/7d
    y cambio diario de una chain.
  - **Fees/revenue** (`GET /defi/fees`): fees agregados de protocolos de
    una chain, 24h/7d y cambio diario.

  - **Yields de lending/staking/LP** (`GET /defi/yields`): vía
    `yields.llama.fi/pools` (DeFiLlama, gratis, sin key) — >15,000 pools
    agregados de todos los protocolos/chains en una sola consulta,
    resolviendo lo que antes parecía requerir pedir protocolo por
    protocolo. Filtros los declara quien consulta (`chain`,
    `stablecoin_only`, `min_tvl_usd`, `limit`); **pools con TVL bajo se
    excluyen por defecto** (`min_tvl_usd=1M`) porque son más fáciles de
    manipular con APY artificialmente inflado, y los que DeFiLlama marca
    como `outlier` (estadísticamente atípicos) se excluyen siempre.
    Probado con datos reales: top yields de Ethereum y filtro
    stablecoin-only funcionando en vivo.

  Token unlocks/vesting sigue sin fuente gratis (DeFiLlama lo movió a su
  API de pago durante este trabajo).

  **Ethereum** (`adapters/onchain/etherscan_adapter.py`): conectado vía
  Etherscan API V2 (`chainid=1`), misma lógica de flujo/anomalía/umbral
  dinámico compartida con Bitcoin
  (`adapters/onchain/_wallet_flow_common.py`, extraída durante este trabajo
  para no duplicarla). Requiere `ETHERSCAN_API_KEY` en `.env` — sin key
  configurada se comporta igual que el resto de adapters (vacío, no falla;
  probado sin key real). Cubre transferencias nativas de ETH (`txlist`) vía
  `GET /onchain/wallet-flow?chain=ethereum`.
  - **Transferencias ERC-20** (`GET /onchain/token-transfers`): endpoint
    `tokentx` de Etherscan, agregado por contrato (inflow/outflow/net/tx
    count), top 15 tokens por volumen — wallets activas reciben decenas de
    airdrops/spam irrelevantes. **El símbolo del token lo define el propio
    contrato y no es confiable**: verificado con datos reales (dirección
    pública de vitalik.eth) que existen múltiples contratos distintos
    usando el símbolo "VITALIK" simultáneamente (tokens impostores/spam,
    común en Ethereum) — por eso se agrupa por `contractAddress`, nunca por
    símbolo, y este sistema no verifica legitimidad de contratos ni intenta
    filtrar spam más allá del top-N por volumen.
  - **Network health de Ethereum** (`GET /onchain/network-health?chain=ethereum`):
    gas price actual (Etherscan `gastracker&action=gasoracle`) convertido a
    USD con precio ETH/USD de CoinGecko, para una transferencia estándar de
    21,000 gas — probado con datos reales (~$0.004 en el momento de la
    prueba). **`hash_rate` queda `None` a propósito**: Ethereum es
    Proof-of-Stake desde The Merge (2022), no existe hash rate que
    reportar. `tx_count_24h` y ambos `*_change_30d_pct` también quedan
    `None`: el histórico de gas price (`stats&action=dailyavggasprice`) es
    exclusivo del plan Pro de Etherscan (verificado en vivo, responde
    "trying to access an API Pro endpoint") — se prefirió dejar el campo
    vacío en vez de estimarlo sin fuente real.

  Fuera de alcance incluso con esto: **MVRV/SOPR/NUPL/Coin Days
  Destroyed/Realized Cap** (requieren análisis de cohortes de UTXO por edad
  sobre el historial completo de la blockchain — inviable sin un proveedor
  de pago o un indexador propio), y **wallet labeling automático/completo**
  (requiere un proveedor como Arkham/Nansen — este sistema solo analiza
  wallets que tú le indiques explícitamente).
- **Narrativa social** (`adapters/narrative/`): X es de pago ahora (el tier
  gratis es inutilizable para análisis real) y Discord/Telegram no tienen
  APIs públicas de búsqueda — quedan fuera sin importar el proveedor.
  Reddit bloquea acceso sin OAuth (probado: 403 en el endpoint público de
  solo lectura). Con eso descartado, conectado con 3 fuentes reales:
  - **GitHub** (`adapters/narrative/github_adapter.py`, gratis, sin key):
    actividad de desarrollo de un repo — estrellas, issues abiertos, y una
    **ratio de aceleración** (commits de los últimos N días vs. los N días
    anteriores) como proxy de si el desarrollo de un proyecto está
    acelerando o desacelerando. 60 req/hora sin key, 5000 con
    `GITHUB_TOKEN` opcional.
  - **Medium** (`adapters/narrative/medium_adapter.py`, gratis, sin key):
    RSS por tag (ej. `defi`, `layer-2`, `artificial-intelligence`),
    reutilizando el mismo scorer de sentimiento por léxico que noticias.
    Solo expone los ~10-25 artículos más recientes, sin control de ventana.
  - **Reddit** (`adapters/narrative/reddit_adapter.py`): código listo (OAuth
    `client_credentials`, posts marcados nivel C/rumor per spec), pero
    **bloqueado por política de la plataforma, no por falta de esfuerzo**:
    Reddit ahora exige un proceso de solicitud manual con "caso de uso de
    moderación" para nuevas apps de su Data API — el registro instantáneo
    tipo NewsAPI/FRED/Etherscan ya no existe. Nuestro caso de uso (análisis
    de sentimiento cripto/financiero) no encaja en esa justificación, así
    que se descartó en vez de someter una solicitud con baja probabilidad
    de aprobación. Sin `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`
    configurados, el adapter devuelve vacío sin fallar (probado) — si en el
    futuro cambia la política de Reddit, solo hay que agregar las
    credenciales, el código ya funciona.

  El repo/tag/subreddit siempre lo declara quien consulta — igual que con
  las wallets, este sistema no preselecciona qué proyecto "representa" una
  narrativa. Expuesto en `GET /narrative/github-activity`,
  `/narrative/medium-tag`, `/narrative/reddit-subreddit`.
- **Calendario de eventos** (`adapters/calendar/`):
  - **Halving BTC** (`GET /calendar/halving-countdown`): determinístico
    (cada 210,000 bloques exactos), no depende de fuente externa.
  - **Gobernanza DAO** (`adapters/calendar/snapshot_adapter.py`, Snapshot.org,
    gratis y sin key): propuestas activas/cerradas de un espacio DAO
    declarado por quien consulta (ej. `stakedao.eth`, `ens.eth`) — probado
    con datos reales. `GET /calendar/governance`.
  - **Token unlocks/vesting**: la API de DeFiLlama para esto pasó a ser de
    pago durante este trabajo (verificado en vivo: 402 en
    `api.llama.fi/emissions/*`) — sin fuente gratuita alternativa
    encontrada, queda pendiente.
  - **Airdrops, hard forks, eventos regulatorios**
    (`adapters/calendar/coinmarketcal_adapter.py`, CoinMarketCal API v2):
    conectado y **probado con datos reales** (registro en
    coinmarketcal.com/developer — ojo, no confundir con coinmarketcap.com,
    son productos distintos con marcas parecidas). Requiere
    `COINMARKETCAL_API_KEY` en `.env`; sin key, vacío, no falla. `coins` se
    filtra por **slug** del proyecto, no por ticker (los tickers colisionan
    entre proyectos distintos, según su propia doc). El plan Free solo trae
    eventos en una ventana de 7 días hacia adelante (90 días en Standard,
    completo en Pro+) — un `total: 0` suele ser justo eso, no un error;
    verificado consultando varios proyectos (`bitcoin`/`ethereum`/`solana`
    sin eventos esa semana, `cardano` con 2 eventos reales). Respeta la
    regla explícita de su API: cuando `isEstimated=true` la fecha es un
    límite/ventana, no un dato literal — se expone `displayed_date`
    (listo para mostrar) además de `date` (para ordenar/filtrar), nunca se
    renderiza `date` directo. `GET /calendar/events`.

    Nota de proceso: la primera versión de este adapter apuntaba a una API
    v1 (`developers.coinmarketcal.com`) que ya no existe — daba 403 con
    cualquier key, incluida la real del usuario. Se diagnosticó mal como
    "key equivocada" antes de encontrar la documentación viva v2
    (`api.coinmarketcal.com`) y reescribir el adapter contra el formato
    real.
- **Correlación cross-asset** (`adapters/market_data/cross_asset_correlation_adapter.py`):
  conectado vía `yfinance`, mismo patrón que `PortfolioManager`. Corrige un
  desfase de timezone real encontrado en pruebas (cripto en UTC vs. índices
  en la tz de su bolsa, ej. `America/New_York`) que hacía que ningún par
  cripto↔tradicional se calculara.

Cada fuente implementa una interfaz común en `alpha_os/adapters/base.py`, así
que cambiar a un proveedor de pago (Polygon, Bloomberg, etc.) más adelante es
un solo archivo nuevo, no un rediseño.

## Market Regime Intelligence

`alpha_os/engine/market_regime_engine.py` — capa de contexto de prioridad
alta del spec: **no genera señales de compra/venta por sí misma**, clasifica
el régimen actual del mercado y reescala (multiplica, no reemplaza) el peso
de los factores ya calculados por `SignalEngine` antes de sumarlos al score.

Tres ejes independientes, construidos sin fuentes nuevas (reutiliza
`^GSPC`/`^VIX` vía `yfinance` y la tendencia de tasas ya calculada por
`FREDMacroAdapter`):
- **Tendencia** (`bull_market_expansion` / `bull_market_exhaustion` /
  `sideways_range` / `bear_market_distribution` / `bear_market_capitulation`):
  SMA50 vs SMA200 + drawdown desde el máximo de 52 semanas + volatilidad
  anualizada del índice de referencia.
- **Riesgo** (`risk_on` / `risk_off`): nivel de VIX; si no está disponible,
  usa la volatilidad realizada del índice de referencia como proxy explícito.
- **Liquidez** (`liquidity_expansion` / `liquidity_contraction`): la misma
  tendencia de fed funds rate ya calculada para el factor `macro_risk_controlled`.

Expuesto en `GET /market-context/regime`. Ejemplo real (S&P 500, hoy):
expansión alcista + risk-on + contracción de liquidez (tasas por encima de
la neutral estimada) → sube el peso de `trend_direction`/`weekly_momentum`/
`macd_confirmation` (contexto alcista) y de `macro_risk_controlled`/
`fundamental_health` (contexto restrictivo). Verificado end-to-end: AAPL
pasó de score 50 a 61 solo por el reescalado de régimen, sin cambiar ningún
factor subyacente.

El umbral de confianza (`SIGNAL_CONFIDENCE_THRESHOLD`, default 45 en
`.env.example`) es un punto intermedio: exige varios factores convergentes
(técnico + fundamentales + sentimiento + macro + institucional, ahora
reescalados por régimen) sin llegar a la alineación casi perfecta que
exigiría el 70 original del spec.

## Broker — Interactive Brokers (paper trading)

`alpha_os/adapters/broker/ibkr_adapter.py` — conecta con TWS o IB Gateway
corriendo **localmente** en la máquina del usuario (así funciona la API de
IBKR, nunca en la nube), vía `ib_async`. Requiere que el usuario tenga la
sesión iniciada ahí y la API habilitada (Configure > API > Settings >
Enable ActiveX and Socket Clients, con "Permitir conexiones solo de
localhost" activado — comportamiento por defecto, no requiere agregar
`127.0.0.1` a mano). Sin TWS/Gateway corriendo, los métodos devuelven
vacío/rechazado sin fallar, igual que el resto de adapters de este sistema
sin su fuente disponible.

**Solo opera órdenes contra cuentas de práctica** (prefijo de cuenta `DU`,
convención de IBKR): `place_test_order` se niega a enviar la orden si la
cuenta conectada no lo es — este sistema nunca coloca órdenes en dinero
real, sin importar qué pida quien llama.

- **Resumen de cuenta** (`GET /broker/account-summary`): liquidación neta,
  cash, poder de compra y posiciones, leídos directo del broker.
  `is_paper_account` se deriva del prefijo real de la cuenta, nunca se
  asume.
- **Posiciones** (`GET /broker/positions`): lo que IBKR reporta que
  realmente tienes — fuente de verdad externa, distinta de las posiciones
  que este sistema crea internamente al generar una señal
  (`OperationEntry`).
- **Orden de prueba** (`POST /broker/test-order`): envía una orden real
  (MKT o LMT) a la cuenta paper. `status` es siempre el estado tal como lo
  reporta IBKR (`Filled`, `Submitted`, `PendingSubmit`...), nunca forzado —
  verificado en vivo: con el mercado cerrado (fin de semana), una orden de
  compra de AAPL quedó en `PendingSubmit` en vez de fabricarse como
  `Filled`.

Probado end-to-end con una cuenta paper real de IBKR (`DUQ282112`,
$1,000,000 virtuales): resumen de cuenta correcto y una orden de compra de
AAPL aceptada por el broker con `order_id` real asignado.

## Tests

```bash
pytest tests/ -v
```
Cubren los requisitos explícitos del módulo institucional: volumen alto no
genera dirección por sí solo, Form 4 diferencia compra/venta de ejercicio de
opciones, contradicciones reducen la confianza, fuentes faltantes devuelven
`insufficient_data`, una falla de API no derriba el motor, el veto de
distribución/acumulación fuerte funciona en ambas direcciones, un 13F de un
solo trimestre no genera señal (no hay con qué comparar), y una posición 13F
nunca se trata como tiempo real sin importar qué tan reciente sea el filing.

También cubren Market Regime Intelligence (clasificación de tendencia/riesgo/
liquidez con series sintéticas controladas, fallback de VIX a proxy,
confianza reducida cuando falta una fuente), los factores cripto
(apalancamiento extremo nunca confirma la hipótesis, solo advierte;
crecimiento de stablecoins solo respalda long, nunca short; ajustes de
régimen rescalan el factor correcto y dejan los demás intactos), y el
wallet flow on-chain (label/source/confidence nunca se fabrican ni se
sobreescriben, detección de anomalías con baseline plano, umbral dinámico
de transacciones grandes robusto a su propio outlier). También cubren los
adapters de narrativa (ratio de actividad de GitHub, parseo y sentimiento de
RSS de Medium, y que Reddit sin credenciales no intenta llamada de red), los
adapters de calendario (parseo de gobernanza Snapshot, CoinMarketCal sin key
no intenta llamada de red, halving determinístico correcto en el límite
exacto de bloque), y que el propio halving avanza correctamente al próximo
ciclo de 210,000 bloques. También cubren aprendizaje continuo: una posición
sobrevive entre instancias distintas de `SQLiteJSONStore` apuntando al mismo
archivo (simula un reinicio real del servidor), post-mortem exige posición
cerrada y `original_signal` presente (nunca fabrica uno sin evidencia), y
el reporte de desempeño por factor marca `has_sufficient_sample=false` por
debajo de 10 ocurrencias y `true` en o por encima de ese umbral. También
cubren el portafolio multi-activo: exposición por clase de activo, filtro
de correlación por umbral, y que las notas de riesgo sistémico solo se
disparan cuando el régimen real lo amerita (alta volatilidad + concentración
cripto, o mercado bajista + exposición larga en equities) — no en cualquier
combinación.

Ninguna señal generada por este sistema debe tratarse como asesoría de
inversión personalizada. Es una herramienta de análisis que tú operas.

## Alpha Brief — pantalla principal

`GET /` sirve `alpha_os/static/index.html`: una pantalla narrativa en
español (tema oscuro, sin frameworks, HTML/CSS/JS plano) que reemplaza a
Swagger como primera pantalla — `/docs` sigue disponible para depuración,
pero ya no es lo primero que se ve. Todo lo que muestra sale de
`GET /brief` (`alpha_os/api/routes_brief.py`), que **agrega salidas ya
existentes** (MarketRegimeEngine, PositionManager, SignalEngine,
LearningEngine) — no calcula nada nuevo, solo compone.

- **Market Pulse**: régimen de mercado (tendencia/riesgo/liquidez) +
  confianza + el texto de `justification` tal cual, sin adornar.
- **Titulares**: nuevo `NewsAPIAdapter.get_market_headlines()` vía
  `/v2/top-headlines?category=business` (antes el adapter solo buscaba por
  ticker vía `/v2/everything`) — mismo filtro de spam y tier por dominio.
- **Mis posiciones**: cada una con su **reevaluación de tesis real**.
  `PositionManager.reassess_thesis()` (antes un stub que lanzaba
  `NotImplementedError`) ahora regenera una señal fresca con el mismo
  SignalEngine y compara contra `original_signal`: dirección, delta de
  conviction_score, y diff de factores por label (qué desapareció/apareció/
  cambió de signo) — construido desde los `rationale` reales de esos
  factores. Sin `original_signal` guardado, dice explícitamente que no hay
  línea base para comparar, en vez de inventar un veredicto.
- **Oportunidades**: escaneo de `settings.watchlist` (ver `WATCHLIST` en
  `.env.example` — el usuario la declara explícitamente, nunca se infiere),
  ordenado por `conviction_score`. Clic en una tarjeta expande `factors` +
  `rationale` completos del `Signal` (cero cálculo nuevo, ya venían en el
  modelo). Advertencia de performance conocida: escanear el watchlist
  entero dispara una llamada real de `SignalEngine.generate_signal()` por
  ticker (yfinance/NewsAPI/FRED/SEC/Binance en vivo) — con 7 tickers,
  `/brief` puede tardar varios segundos.
- **Aprendizaje**: `LearningReport.rationale` tal cual — con una cuenta
  nueva sin posiciones cerradas, dice honestamente que no hay muestra
  todavía.

Fuera de este alcance a propósito, porque no hay dato real que lo respalde
hoy (documentado para no fabricarlo): sentimiento social agregado de
mercado, un gauge único de "Smart Money" a nivel de mercado, y postura por
medio financiero individual (Reuters/Bloomberg/WSJ por separado).

## Bot de trading diario (paper)

`alpha_os/jobs/daily_trading_job.py` cierra el ciclo completo: encuentra
oportunidades (mismo escaneo del watchlist que "Oportunidades") y las
**ejecuta de verdad** en la cuenta paper de IBKR, sin intervención manual.

- **$1,000 por operación** (monto fijo, no % del buying power — decisión
  explícita del usuario). Equities: acciones enteras (si $1,000 no alcanza
  para 1 acción, se omite con motivo explícito). Cripto: cantidad
  fraccionaria.
- **Una vez al día**: loop en background dentro del mismo proceso FastAPI
  (`alpha_os/main.py`, `_daily_trading_loop`), sin dependencia nueva tipo
  `apscheduler`/cron/launchd. Trade-off aceptado: solo corre mientras
  `uvicorn` esté vivo — para la prueba de una semana, hay que dejar el
  servidor corriendo junto con TWS.
- **Nunca duplica posiciones**: si ya hay una posición activa en un ticker,
  ese ticker se salta ese día.
- **Nunca opera en cuenta real**: reutiliza el mismo guardrail de
  `IBKRAdapter.place_test_order` (prefijo de cuenta "DU").
- Toda orden aceptada se registra en `PositionManager` con su
  `original_signal` — así `reassess_thesis`, el post-mortem y
  `LearningEngine` tienen datos reales con qué trabajar al cerrar la semana.
- **Deliberadamente no corre al arrancar el servidor** (`main.py`, ver
  comentario en `_daily_trading_loop`): reiniciar el servidor durante
  desarrollo no debe disparar una corrida real. La primera corrida del día
  se dispara a mano vía `POST /jobs/daily-trading/run-now` (o el botón
  "Ejecutar ahora" en Alpha Brief); de ahí en adelante corre sola cada 24h.
- `GET /jobs/daily-trading/last-run` — último resultado (log legible
  ticker por ticker: operó, se omitió, o se rechazó, y por qué). Se
  muestra en Alpha Brief bajo "Bot de trading diario". No persiste entre
  reinicios del servidor — las posiciones/órdenes reales sí (SQLite + IBKR).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn alpha_os.main:app --reload
```
