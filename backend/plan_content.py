"""
Contenido completo del plan de trading. 
Se sirve via /api/plan/markdown para descarga y /api/plan/data para frontend.
"""

CAPITAL = 800
MAX_RISK_PER_TRADE_PCT = 1.0  # $8 por trade
MAX_DAILY_LOSS_PCT = 3.0  # $24 al día → STOP
MAX_CONSECUTIVE_LOSSES = 3
MIN_RR = 2.0  # 1:2 mínimo

# ====== MCPs ======
MCPS = [
    {
        "id": "news",
        "name": "MCP de Noticias & Calendario",
        "color": "amber",
        "icon": "Newspaper",
        "purpose": "Recolecta calendario económico (ForexFactory) + noticias de fuentes confiables (Reuters, Bloomberg, FT vía Finnhub/NewsAPI). Correlaciona la hora de publicación con la hora actual para decidir si la oportunidad sigue viva o el movimiento ya se descontó.",
        "tools": [
            "get_calendar(date, impact='high|medium|low') → eventos económicos del día",
            "get_news(symbol|topic, since_minutes) → noticias relevantes con timestamp",
            "is_tradeable_now(symbol) → bool + razón (ej: 'High-impact NFP en 15min, NO operar')",
            "news_relevance_score(headline, symbol) → 0-100 (qué tanto afecta al activo)",
        ],
        "env_keys": ["FINNHUB_API_KEY (gratis: finnhub.io)", "NEWSAPI_KEY (gratis: newsapi.org)"],
        "prompt": """Construye un MCP server en Python usando FastMCP llamado "news-mcp".

REQUISITOS:
1. Usa la librería `mcp` (modelcontextprotocol/python-sdk) o `fastmcp`.
2. Lee variables de entorno: FINNHUB_API_KEY, NEWSAPI_KEY.
3. Estructura de archivos:
   ~/mcp/news-mcp/
     ├─ server.py
     ├─ requirements.txt  (mcp, httpx, beautifulsoup4, python-dateutil, pytz)
     └─ .env

4. Implementa estas tools:

   a) get_economic_calendar(date: str = "today", impact: str = "high")
      - Scrapea https://www.forexfactory.com/calendar (User-Agent real)
      - Devuelve lista de {time_utc, currency, event, impact, actual, forecast, previous}
      - Filtra por impact (high/medium/low/all)

   b) get_news(query: str, since_minutes: int = 60, max_items: int = 10)
      - Llama Finnhub /news endpoint (category general/forex/crypto)
      - Si no hay Finnhub, fallback a NewsAPI /v2/everything
      - Filtra solo fuentes confiables: reuters.com, bloomberg.com, ft.com, wsj.com, cnbc.com, marketwatch.com
      - Devuelve {title, source, url, published_at_utc, summary, age_minutes}

   c) is_tradeable_now(symbol: str)
      - Recibe símbolo MT5 (EURUSD, NAS100, XAUUSD, BTCUSD, etc.)
      - Mapea símbolo → divisas/categoría afectada
      - Llama get_economic_calendar y get_news
      - Reglas:
        * Si hay noticia HIGH-impact ±30min → return {tradeable: false, reason: "..."}
        * Si hay noticia <5min vieja con relevance>70 → return {tradeable: false, reason: "movimiento fresco, espera retest"}
        * Si hay noticia 30-90min vieja con relevance>70 → {tradeable: true, caution: "fade-only"}
        * Si no hay nada relevante → {tradeable: true, normal: true}

   d) news_relevance_score(headline: str, symbol: str)
      - Heurística simple por keywords (FOMC, CPI, NFP, geopolitics, etc.)
      - Devuelve 0-100

5. Manejo de errores robusto, timeouts de 10s en todas las llamadas HTTP.
6. No uses Twitter/X bajo ninguna circunstancia.
7. Logging a stderr (los MCP usan stdout para protocolo).

Al final genera el bloque de configuración para `claude_desktop_config.json`:
{
  "mcpServers": {
    "news": {
      "command": "python",
      "args": ["C:\\\\Users\\\\<usuario>\\\\mcp\\\\news-mcp\\\\server.py"],
      "env": { "FINNHUB_API_KEY": "...", "NEWSAPI_KEY": "..." }
    }
  }
}
""",
    },
    {
        "id": "trading",
        "name": "MCP de Trading (MT5)",
        "color": "green",
        "icon": "TrendingUp",
        "purpose": "Conecta con MetaTrader 5 corriendo en Windows nativo. Expone account info, market data y ejecución de órdenes con reglas de seguridad pre-trade integradas (1% riesgo, max 1 posición, R:R mínimo 1:2).",
        "tools": [
            "get_account_info() → balance, equity, margin, P&L del día",
            "get_open_positions() → lista (debe ser ≤1)",
            "get_rates(symbol, timeframe, n) → últimas N velas OHLCV",
            "get_tick(symbol) → bid/ask/spread actual",
            "place_order(symbol, type, lots, sl, tp, comment) → con guardas",
            "close_position(ticket) → cierra por ticket",
            "modify_sl_tp(ticket, sl, tp) → trailing manual",
        ],
        "env_keys": ["MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER (broker)"],
        "prompt": """Construye un MCP server en Python llamado "trading-mt5-mcp".
IMPORTANTE: La librería `MetaTrader5` SOLO funciona en Windows NATIVO (no WSL). Por eso este MCP debe correr con el Python de Windows, no el de WSL.

ESTRUCTURA:
   C:\\Users\\<user>\\mcp\\trading-mt5-mcp\\
     ├─ server.py
     ├─ requirements.txt  (mcp, MetaTrader5, pandas, python-dotenv)
     └─ .env  (MT5_LOGIN, MT5_PASSWORD, MT5_SERVER)

REGLAS DE SEGURIDAD INTEGRADAS (NO NEGOCIABLES, hardcodeadas):
- MAX_RISK_PER_TRADE_PCT = 1.0
- MAX_DAILY_LOSS_PCT = 3.0
- MAX_OPEN_POSITIONS = 1
- MIN_RR = 2.0
- MAX_LOTS_PER_TRADE = 0.5  (sanity cap)
- BLOCKED_HOURS_UTC = [(21,0,23,59), (0,0,7,0)]  (no operar de noche)

TOOLS:

1) initialize_mt5()
   - mt5.initialize(login=..., password=..., server=...)
   - Devuelve {connected: bool, account: ...}

2) get_account_info()
   - mt5.account_info() → {balance, equity, margin_free, profit, leverage}
   - Calcula daily_pl leyendo deals del día con mt5.history_deals_get
   - Devuelve daily_pl_pct también

3) get_open_positions()
   - mt5.positions_get() → lista normalizada

4) get_rates(symbol, timeframe="M15", n=200)
   - timeframe: M1, M5, M15, M30, H1, H4, D1
   - Devuelve DataFrame as records (open, high, low, close, volume, time)

5) get_tick(symbol)
   - mt5.symbol_info_tick(symbol) → {bid, ask, spread, time}

6) calculate_lot_size(symbol, sl_pips, risk_pct=1.0)
   - balance × risk_pct% / (sl_pips × tick_value)
   - Redondea al lot_step del símbolo

7) place_order(symbol, side, lots, sl, tp, comment="claude")
   - side: "buy" | "sell"
   - PRE-CHECKS (si falla, return {ok: false, reason})
     a) account.daily_pl_pct <= -3.0 → "DAILY LOSS LIMIT"
     b) len(open_positions) >= 1 → "MAX 1 POSITION"
     c) sl is None or tp is None → "SL Y TP OBLIGATORIOS"
     d) Calcular R:R: abs(tp-entry)/abs(sl-entry) < 2.0 → "R:R MENOR A 1:2"
     e) lots > MAX_LOTS_PER_TRADE → "LOT SIZE EXCEDE CAP"
     f) hora UTC en BLOCKED_HOURS → "FUERA DE HORARIO PERMITIDO"
     g) risk_calculado > 1% del balance → "RIESGO EXCEDE 1%"
   - Si pasa todas: mt5.order_send(request)
   - Loguea siempre el intento (aceptado o rechazado) a archivo /logs/orders.jsonl

8) close_position(ticket) y modify_sl_tp(ticket, sl, tp)

9) get_trade_history(days=7)
   - history_deals_get → P&L por trade

CONFIG claude_desktop_config.json:
{
  "mcpServers": {
    "trading": {
      "command": "C:\\\\Python311\\\\python.exe",
      "args": ["C:\\\\Users\\\\<usuario>\\\\mcp\\\\trading-mt5-mcp\\\\server.py"],
      "env": { "MT5_LOGIN": "...", "MT5_PASSWORD": "...", "MT5_SERVER": "..." }
    }
  }
}

NOTA: La cuenta DEMO debe usarse PRIMERO durante 2 semanas. Solo cambiar a real ($800) cuando pasemos auditoría de 40+ trades demo con expectancy positiva.
""",
    },
    {
        "id": "analysis",
        "name": "MCP de Análisis Técnico",
        "color": "blue",
        "icon": "LineChart",
        "purpose": "Calcula indicadores (RSI, EMA, ATR, MACD, SuperTrend), detecta estructura de mercado (HH/HL/LH/LL), identifica soportes/resistencias y patrones de vela. Trabaja en multi-temporalidad para confirmar setups.",
        "tools": [
            "indicators(symbol, tf, n) → {ema20,50,200, rsi14, atr14, macd}",
            "market_structure(symbol, tf) → uptrend|downtrend|range + HH/HL análisis",
            "support_resistance(symbol, tf, n=200) → niveles con touches",
            "candlestick_patterns(symbol, tf) → último patrón si lo hay",
            "mtf_bias(symbol) → bias H4 + alineación M15",
            "score_setup(symbol, side, entry, sl, tp) → 0-100 (qualidad del setup)",
        ],
        "env_keys": ["(usa get_rates del MCP trading vía recursos)"],
        "prompt": """Construye un MCP server en Python "analysis-mcp" que NO se conecta a MT5 directamente sino que recibe arrays OHLCV como argumentos.

DEPENDENCIAS: pandas, numpy, pandas-ta (o talib si está disponible).

TOOLS:

1) indicators(ohlcv: list[dict], periods: dict = None)
   - Recibe lista de {time, open, high, low, close, volume}
   - Calcula: EMA(20,50,200), SMA(20), RSI(14), ATR(14), MACD(12,26,9), 
     Bollinger Bands(20,2), VWAP intradía, SuperTrend(10,3)
   - Devuelve dict con valores actuales + previos (para detectar cruces)

2) market_structure(ohlcv: list[dict], swing_n: int = 5)
   - Detecta swing highs/lows (pivotes de N velas)
   - Clasifica últimos 4 swings:
     - Uptrend: HH+HL
     - Downtrend: LH+LL
     - Range: alternados
   - Devuelve {trend, last_4_swings, breakout_zone}

3) support_resistance(ohlcv: list[dict], min_touches: int = 2, tolerance_pct: float = 0.15)
   - Cluster de máximos/mínimos cercanos
   - Cuenta touches y devuelve niveles ordenados por fuerza

4) candlestick_patterns(ohlcv: list[dict])
   - Detecta últimas 3 velas: pin bar, engulfing, doji, inside bar, fakey
   - Devuelve {pattern, bias_implied, confidence}

5) mtf_bias(ohlcv_h4: list, ohlcv_m15: list)
   - Bias H4: arriba EMA200 → bullish, abajo → bearish
   - Alineación M15: si ambos alineados devuelve {aligned: true, side: "buy"|"sell"}

6) score_setup(ohlcv, side, entry, sl, tp)
   - Suma puntos:
     +25 si trend M15 alineado con side
     +20 si MTF aligned (H4+M15)
     +15 si en zona de S/R con ≥2 touches
     +10 si patrón de vela en favor
     +10 si RSI no extremo (30-70 para entries en pullback)
     +10 si R:R ≥ 2.5
     +10 si ATR no en mínimos (mercado activo)
   - Devuelve {score, breakdown, recommendation: "TAKE"|"SKIP"|"WAIT"}
   - Solo recomendamos TAKE si score >= 70

NOTA: Este MCP es PURO (sin estado, sin red). Recibe data, devuelve análisis. 
La data viene del MCP trading vía Claude orchestration.
""",
    },
    {
        "id": "risk",
        "name": "MCP de Gestión de Riesgo",
        "color": "red",
        "icon": "ShieldAlert",
        "purpose": "Guardian de la cuenta. Calcula tamaño de posición exacto, monitorea drawdown del día, bloquea trading tras 3 pérdidas consecutivas o -3% diario. Lleva contabilidad de la equity y emite señal de STOP.",
        "tools": [
            "calc_position_size(balance, risk_pct, entry, sl, symbol) → lots",
            "daily_status(balance, deals_today) → {dd_pct, trades_count, can_trade}",
            "should_stop_trading(deals_today) → {stop, reason}",
            "register_trade(result) → actualiza state",
            "expectancy(last_n_trades) → win_rate, avg_R, expectancy",
        ],
        "env_keys": [],
        "prompt": """Construye un MCP server en Python "risk-mcp" que actúa como guardia de la cuenta.

ESTADO PERSISTENTE: archivo JSON en ~/mcp/risk-mcp/state.json con:
{
  "starting_balance_today": 800,
  "deals_today": [],
  "consecutive_losses": 0,
  "locked_until_utc": null,  // si hit -3% queda lockeado hasta 00:00 UTC
  "last_reset_date": "2026-01-15"
}
Auto-reset al cambiar de día UTC.

TOOLS:

1) calc_position_size(balance: float, risk_pct: float, entry: float, sl: float, 
                       contract_size: float, tick_value: float, tick_size: float)
   - risk_dollars = balance * (risk_pct/100)
   - sl_distance = abs(entry - sl)
   - sl_ticks = sl_distance / tick_size
   - dollars_per_lot = sl_ticks * tick_value
   - lots = risk_dollars / dollars_per_lot
   - Devuelve {lots, risk_dollars, sl_distance, warnings: []}

2) daily_status()
   - Lee state.json
   - Calcula dd_pct = sum(deals.profit) / starting_balance * 100
   - Devuelve {dd_pct, trades_count, consecutive_losses, can_trade, locked: bool, reason}

3) should_stop_trading()
   - Reglas STOP:
     a) dd_pct <= -3.0 → STOP día
     b) consecutive_losses >= 3 → STOP día
     c) trades_count >= 5 → STOP (sobre-trading)
     d) hora UTC > 21:00 → STOP nocturno
   - Devuelve {stop: bool, reason: str, resume_at: datetime}

4) register_trade(profit: float, r_multiple: float, symbol: str, side: str)
   - Append a deals_today
   - Si profit < 0: consecutive_losses += 1, sino reset a 0
   - Si dd hit -3%: set locked_until_utc = next_day_00_utc
   - Persiste state.json

5) expectancy(last_n: int = 30)
   - Lee history (deals.jsonl)
   - win_rate = wins/total
   - avg_R = mean(r_multiples)
   - expectancy = (win_rate * avg_win_R) - ((1-win_rate) * avg_loss_R)
   - Devuelve {win_rate, avg_R, expectancy, n}

6) reset_day() (admin)
   - Solo si fecha cambió. Auto-llamado.

NOTA: Este MCP es la "última línea de defensa". Aunque Claude se equivoque o el trading-mcp falle, este debe gritar STOP cuando toque.
""",
    },
]

# ====== ESTRATEGIAS (6 setups validados) ======
STRATEGIES = [
    {
        "id": "orb",
        "name": "Opening Range Breakout (ORB)",
        "type": "Intradía",
        "best_for": "Índices (NAS100, US30, DAX, SP500)",
        "session": "Apertura NY 14:30-16:00 UTC",
        "rr": "1:2 a 1:3",
        "expected_winrate": "45-55%",
        "rules": [
            "Marca High y Low de los primeros 15min de la sesión NY",
            "Espera ruptura del rango con vela de impulso (cierre > High o < Low)",
            "Entrada en retest del nivel roto (no chase)",
            "Stop: en el lado opuesto del rango (15-25 pips típicamente)",
            "Target 1: 1.5R (parcial 50%) — Target 2: 3R (mover SL a BE)",
            "Invalidación: si vuelve dentro del rango antes del retest",
        ],
        "filters": [
            "MCP News: NO operar si hay noticia HIGH ±30min",
            "MCP Analysis: bias H4 alineado con la dirección de ruptura",
            "ATR del día > 0.7 × ATR(14) promedio (volatilidad mínima)",
        ],
        "color": "green",
    },
    {
        "id": "ema-pullback",
        "name": "EMA 200 Pullback",
        "type": "Intradía",
        "best_for": "Forex majores (EURUSD, GBPUSD, USDJPY)",
        "session": "Londres 08:00-12:00 UTC",
        "rr": "1:2",
        "expected_winrate": "50-60%",
        "rules": [
            "H4: precio claramente por encima/debajo de EMA200 (tendencia)",
            "M15: precio se acerca a EMA50 o EMA200 (pullback en tendencia)",
            "Buscar vela de rechazo (pin bar, engulfing) en EMA",
            "Entrada en cierre de vela de confirmación",
            "Stop: 1×ATR(14) más allá del pin/engulfing",
            "Target: nivel previo de swing high/low (>= 2R)",
        ],
        "filters": [
            "RSI(14) M15 entre 40-60 (no extremo)",
            "Estructura M15: HH+HL (long) o LL+LH (short)",
            "Spread < 1.5 pips",
        ],
        "color": "blue",
    },
    {
        "id": "liquidity-grab",
        "name": "Liquidity Grab + Order Block (SMC)",
        "type": "Intradía",
        "best_for": "Forex majores y XAUUSD",
        "session": "London-NY overlap 12:00-16:00 UTC",
        "rr": "1:3 a 1:5",
        "expected_winrate": "40-50%",
        "rules": [
            "Identifica un Order Block H1 reciente (vela de origen del impulso)",
            "Espera barrida (sweep) del high/low local en M5",
            "Confirmación: cambio de estructura (BOS) en M5 a favor del OB",
            "Entrada: retest del 50% del OB o del FVG creado",
            "Stop: más allá del extremo del sweep + buffer 5 pips",
            "Target: liquidez opuesta (otro swing notable)",
        ],
        "filters": [
            "Solo en confluencia con S/R H1 y bias H4",
            "ATR M5 > promedio (movimiento real, no choppy)",
            "Score setup MCP analysis ≥ 75",
        ],
        "color": "amber",
    },
    {
        "id": "rsi-divergence",
        "name": "RSI Divergencia en Rango",
        "type": "Intradía",
        "best_for": "Oro (XAUUSD), USDJPY",
        "session": "Asia tardía / Londres temprano 06:00-09:00 UTC",
        "rr": "1:2",
        "expected_winrate": "55-65%",
        "rules": [
            "Mercado en rango claro H1 (3+ touches en cada extremo)",
            "Acerca a borde del rango con divergencia RSI(14) M15",
            "Vela de confirmación (rejection wick) en el borde",
            "Entrada en cierre de la vela de rechazo",
            "Stop: 1.2×ATR fuera del rango",
            "Target: parcial en mid-range, total en borde opuesto",
        ],
        "filters": [
            "MTF: H4 también en consolidación (no contra-tendencia fuerte)",
            "Sin noticia HIGH próxima (que rompería el rango)",
            "Spread < 2 pips (oro: < 30 puntos)",
        ],
        "color": "blue",
    },
    {
        "id": "daily-trend-carry",
        "name": "Daily Trend Carry (Overnight)",
        "type": "Swing 1-3 días",
        "best_for": "Forex majores, Índices",
        "session": "Entrada en cierre Diario NY (21:00 UTC)",
        "rr": "1:3 a 1:5",
        "expected_winrate": "40-50%",
        "rules": [
            "D1: SuperTrend(10,3) y EMA50 mismo lado, ≥3 días alineados",
            "Pullback a EMA20 D1 sin perderla (cierre por encima/debajo)",
            "Confirmación H4: vela de continuación al cierre del día",
            "Entrada: al cierre de la vela diaria (21:00 UTC)",
            "Stop: bajo el último swing low (uptrend) — dist típica 1.5×ATR D1",
            "Target: extensión 1.618 del último swing previo",
        ],
        "filters": [
            "Cuidado con spread overnight (algunos brokers triple lunes)",
            "Reducir size 30% por riesgo de gap",
            "Calendar: chequear noticias siguientes 48h",
        ],
        "color": "green",
    },
    {
        "id": "news-fade",
        "name": "News Fade (Reactiva)",
        "type": "Reactiva",
        "best_for": "Forex en NFP/CPI/FOMC",
        "session": "Solo en publicaciones programadas",
        "rr": "1:2",
        "expected_winrate": "45-55%",
        "rules": [
            "ESPERA 30min después de la noticia (no operar la primera barrida)",
            "Identifica el high/low post-noticia en M5",
            "Espera retest sin romperlo (rejection)",
            "Entrada en cierre de vela de retest fallido",
            "Stop: 5 pips más allá del extremo post-news",
            "Target: 50% del recorrido inicial de la noticia (hacia el medio)",
        ],
        "filters": [
            "Solo en noticias HIGH-impact (NFP, CPI, FOMC, GDP)",
            "Spread debe haberse normalizado (< 2× normal)",
            "Si tras 90min no hay setup claro → SALIR del activo",
        ],
        "color": "red",
    },
]

# ====== REGLAS ESTRICTAS ======
STRICT_RULES = [
    {"id": "r1", "rule": "Riesgo por trade: máximo 1% = $8 USD", "category": "MONEY", "severity": "critical"},
    {"id": "r2", "rule": "Pérdida diaria máxima: 3% = $24 USD → STOP día completo", "category": "MONEY", "severity": "critical"},
    {"id": "r3", "rule": "3 pérdidas consecutivas → STOP día completo", "category": "MONEY", "severity": "critical"},
    {"id": "r4", "rule": "Solo 1 posición abierta a la vez. NUNCA dos.", "category": "EXECUTION", "severity": "critical"},
    {"id": "r5", "rule": "R:R mínimo 1:2. Si no hay 1:2 visible, no hay trade.", "category": "EXECUTION", "severity": "critical"},
    {"id": "r6", "rule": "Stop Loss SIEMPRE puesto ANTES de la entrada (no 'después')", "category": "EXECUTION", "severity": "critical"},
    {"id": "r7", "rule": "Take Profit definido antes de entrar (al menos TP1)", "category": "EXECUTION", "severity": "high"},
    {"id": "r8", "rule": "Blackout: 30 min antes y después de cualquier noticia HIGH-impact", "category": "TIMING", "severity": "high"},
    {"id": "r9", "rule": "No operar viernes después de 17:00 UTC (cierre de semana)", "category": "TIMING", "severity": "high"},
    {"id": "r10", "rule": "No operar lunes antes de 08:00 UTC (apertura caótica)", "category": "TIMING", "severity": "medium"},
    {"id": "r11", "rule": "Máximo 5 trades/día. Si llevas 5, día terminado.", "category": "EXECUTION", "severity": "high"},
    {"id": "r12", "rule": "Si dudas del setup → NO operes. Mejor perder oportunidad que dinero.", "category": "MINDSET", "severity": "critical"},
    {"id": "r13", "rule": "NUNCA mover el SL en contra (alejarlo). SOLO a favor.", "category": "EXECUTION", "severity": "critical"},
    {"id": "r14", "rule": "NUNCA promediar pérdidas (no añadir a posición perdedora)", "category": "EXECUTION", "severity": "critical"},
    {"id": "r15", "rule": "Después de TP1, mover SL a Break Even mínimo", "category": "EXECUTION", "severity": "high"},
    {"id": "r16", "rule": "Diario obligatorio: cada trade se registra en el journal con razón", "category": "DISCIPLINE", "severity": "high"},
    {"id": "r17", "rule": "Score MCP-analysis < 70 → SKIP. No fuerces setups B.", "category": "EXECUTION", "severity": "high"},
    {"id": "r18", "rule": "Si llevas día verde +2R → considera parar (proteger ganancias)", "category": "MINDSET", "severity": "medium"},
    {"id": "r19", "rule": "Spread máximo: forex < 2.5 pips, oro < 35pts, índices < 2pts", "category": "EXECUTION", "severity": "high"},
    {"id": "r20", "rule": "Demo primero 2 semanas / 40+ trades antes de tocar la cuenta real", "category": "DISCIPLINE", "severity": "critical"},
]

# ====== CHECKLIST DIARIO ======
CHECKLIST_TEMPLATE = {
    "pre_market": [
        {"id": "pm1", "text": "Revisar calendario económico del día (MCP news → get_economic_calendar)"},
        {"id": "pm2", "text": "Revisar P&L cuenta y daily_status (MCP risk → daily_status)"},
        {"id": "pm3", "text": "Identificar 2-3 activos candidatos del día con mejor score"},
        {"id": "pm4", "text": "Marcar niveles clave H4 (S/R, EMA200, último swing)"},
        {"id": "pm5", "text": "Definir plan A y plan B por escrito (qué busco, dónde NO entro)"},
        {"id": "pm6", "text": "Estado mental: ¿dormí bien? ¿problemas personales? Si NO → no operar"},
        {"id": "pm7", "text": "Confirmar lockout NO activo (risk-mcp → should_stop_trading)"},
    ],
    "during_market": [
        {"id": "dm1", "text": "Esperar setup A+ (score ≥ 70). Setups B = SKIP"},
        {"id": "dm2", "text": "ANTES de entrar: SL y TP definidos en pantalla"},
        {"id": "dm3", "text": "Verificar 'is_tradeable_now' del MCP news antes de send order"},
        {"id": "dm4", "text": "Una vez en trade: NO añadir, NO mover SL en contra, NO 'esperar más'"},
        {"id": "dm5", "text": "Tras TP1 → mover SL a Break Even"},
        {"id": "dm6", "text": "Si pierdo 2 seguidas → revisar journal antes del 3er trade"},
    ],
    "post_market": [
        {"id": "po1", "text": "Cerrar todas las posiciones intradía si aplica (revisar swing)"},
        {"id": "po2", "text": "Registrar TODOS los trades en el journal (entry, exit, R, razón, screenshot)"},
        {"id": "po3", "text": "Calcular expectancy de los últimos 20 trades (MCP risk → expectancy)"},
        {"id": "po4", "text": "Anotar 1 cosa que hice bien + 1 cosa a mejorar"},
        {"id": "po5", "text": "Cerrar plataforma. No mirar más cuenta hasta mañana."},
    ],
}

# ====== MINDSET ======
MINDSET_PRINCIPLES = [
    {
        "title": "El mercado no te debe nada",
        "body": "Has perdido miles antes. Eso fue el precio del aprendizaje. La cuenta de $800 no es para 'recuperar', es para EJECUTAR un sistema con disciplina. Recuperar es consecuencia, no objetivo.",
    },
    {
        "title": "Tu enemigo es tu impaciencia, no el broker",
        "body": "Los pierde-todo no perdieron por falta de estrategia, perdieron por entrar sin esperar el setup, por revenge-trade después de una pérdida, y por aumentar size cuando 'estaban seguros'. Las reglas existen para protegerte de ti mismo.",
    },
    {
        "title": "1% no es poco, es exactamente lo correcto",
        "body": "Con $800 y 1%, cada trade arriesga $8. Con expectancy +0.4R y 3 trades/día = $9.6/día = ~$200/mes (25% mensual). Esto es brutal. Pero requiere AÑOS de constancia. Acepta el viaje.",
    },
    {
        "title": "Claude no es tu salvador, es tu copiloto",
        "body": "Los MCPs te dan superpoderes de análisis, pero la última firma la pones tú. Si Claude dice 'TAKE' y tú no lo ves claro, NO ENTRES. Si Claude dice 'SKIP' y tú lo ves clarísimo, ANOTA en journal por qué y SKIP igual. Por dos semanas mínimo. Después podemos revisar override.",
    },
    {
        "title": "El día verde se PROTEGE",
        "body": "Si abres con +2R, la matemática dice que el siguiente trade tiene esperanza negativa por psicología (ganador eufórico = sloppy). Apaga. Mañana hay más mercado.",
    },
    {
        "title": "Journaling no es opcional",
        "body": "Sin diario detallado, repites errores. Cada trade: screenshot pre-entrada, screenshot post-salida, razón de entrada, lo que aprendiste. 30 trades documentados valen más que 300 ejecutados a ciegas.",
    },
]

# ====== SETUP GUIDE ======
SETUP_GUIDE = [
    {
        "step": 1,
        "title": "Preparar Windows + WSL",
        "commands": [
            "# En PowerShell admin:",
            "wsl --install -d Ubuntu-22.04",
            "# Reiniciar Windows",
            "# Dentro de WSL:",
            "sudo apt update && sudo apt upgrade -y",
            "sudo apt install -y python3.11 python3.11-venv python3-pip git curl",
        ],
    },
    {
        "step": 2,
        "title": "Instalar Python en Windows nativo (REQUERIDO para MT5 MCP)",
        "commands": [
            "# Descargar Python 3.11 desde python.org (instalador Windows)",
            "# Marcar 'Add to PATH' en el instalador",
            "# Verificar en PowerShell:",
            "python --version",
            "pip install MetaTrader5 mcp httpx pandas python-dotenv",
        ],
    },
    {
        "step": 3,
        "title": "Instalar MetaTrader 5 (broker)",
        "commands": [
            "# 1) Descargar MT5 del broker (Pepperstone, IC Markets, Exness, etc.)",
            "# 2) Login con cuenta DEMO primero (NUNCA real al inicio)",
            "# 3) Activar 'Allow algorithmic trading' en Options → Expert Advisors",
            "# 4) Anotar: Login, Password Investor (NO master), Server",
        ],
    },
    {
        "step": 4,
        "title": "Instalar Claude Desktop",
        "commands": [
            "# Descargar de https://claude.ai/download (Windows version)",
            "# Login con tu cuenta Pro Max",
            "# Verificar versión soporta MCPs (Settings → Developer)",
        ],
    },
    {
        "step": 5,
        "title": "Crear estructura de carpetas para MCPs",
        "commands": [
            "# En Windows PowerShell:",
            "mkdir C:\\Users\\$env:USERNAME\\mcp",
            "cd C:\\Users\\$env:USERNAME\\mcp",
            "mkdir news-mcp, trading-mt5-mcp, analysis-mcp, risk-mcp, logs",
        ],
    },
    {
        "step": 6,
        "title": "Construir cada MCP con Claude Code",
        "commands": [
            "# Abre Claude Desktop (o terminal con Claude Code CLI si lo tienes)",
            "# Para cada MCP del dashboard:",
            "#   1) Copia el prompt del MCP (botón Copy en la card)",
            "#   2) Pégaselo a Claude pidiéndole que cree los archivos",
            "#   3) Claude generará server.py, requirements.txt, .env.example",
            "#   4) Guárdalos en la carpeta correspondiente",
            "# Instala dependencias por cada MCP:",
            "cd C:\\Users\\$env:USERNAME\\mcp\\news-mcp",
            "pip install -r requirements.txt",
            "# Repite para los otros 3 MCPs",
        ],
    },
    {
        "step": 7,
        "title": "Configurar claude_desktop_config.json",
        "commands": [
            "# Ubicación: %APPDATA%\\Claude\\claude_desktop_config.json",
            "# Pega los 4 bloques mcpServers (uno por cada MCP)",
            "# Estructura final:",
            "{",
            '  "mcpServers": {',
            '    "news": { "command": "python", "args": ["...news-mcp/server.py"], "env": {...} },',
            '    "trading": { "command": "python", "args": ["...trading-mt5-mcp/server.py"], "env": {...} },',
            '    "analysis": { "command": "python", "args": ["...analysis-mcp/server.py"] },',
            '    "risk": { "command": "python", "args": ["...risk-mcp/server.py"] }',
            "  }",
            "}",
            "# Reiniciar Claude Desktop",
        ],
    },
    {
        "step": 8,
        "title": "Validación con cuenta DEMO (2 semanas mínimo)",
        "commands": [
            "# Días 1-3: Solo testear conexión y herramientas (no trades reales)",
            "#   - Pedir a Claude: 'Verifica conexión MT5 y dame estado cuenta'",
            "#   - 'Trae calendario económico de hoy'",
            "#   - 'Analiza NAS100 M15 últimas 100 velas'",
            "# Días 4-14: Trading manual asistido",
            "#   - Tú decides el setup, Claude valida con MCPs y ejecuta",
            "#   - Mínimo 40 trades documentados",
            "#   - Expectancy debe ser > +0.3R para pasar a real",
        ],
    },
    {
        "step": 9,
        "title": "Migración a cuenta REAL ($800)",
        "commands": [
            "# Solo si:",
            "#  - 40+ trades demo con expectancy > 0.3R",
            "#  - 2 semanas siguiendo TODAS las reglas sin saltarse ninguna",
            "#  - Te sientes ABURRIDO ejecutando (señal de proceso interiorizado)",
            "# Cambia MT5_LOGIN/PASSWORD/SERVER en .env del trading-mcp a la cuenta real",
            "# Empieza con 0.5% riesgo (no 1%) durante 1 semana",
            "# Si todo bien, sube a 1% el riesgo estándar",
        ],
    },
]


def build_markdown() -> str:
    """Construye el plan completo en Markdown para descargar."""
    md = []
    md.append("# PLAN OPERATIVO: Trading de Futuros con Claude Pro Max + MCPs + MT5\n")
    md.append("**Capital inicial:** $800 USD · **Stack:** Windows + WSL + MT5 + Claude Desktop · **Riesgo/trade:** 1%\n")
    md.append("\n> ⚠️ DINERO REAL. Este plan asume haber pasado primero 2 semanas en demo con expectancy positiva.\n")

    md.append("\n## 1. ARQUITECTURA DE MCPs (4 servidores)\n")
    for m in MCPS:
        md.append(f"\n### {m['name']}\n")
        md.append(f"**Propósito:** {m['purpose']}\n\n**Tools expuestas:**\n")
        for t in m["tools"]:
            md.append(f"- `{t}`\n")
        md.append(f"\n**Variables de entorno:** {', '.join(m['env_keys']) or 'ninguna'}\n")
        md.append(f"\n**Prompt para Claude Code:**\n```\n{m['prompt']}\n```\n")

    md.append("\n## 2. ESTRATEGIAS (6 setups validados)\n")
    for s in STRATEGIES:
        md.append(f"\n### {s['name']}  *({s['type']})*\n")
        md.append(f"- **Mejor para:** {s['best_for']}\n")
        md.append(f"- **Sesión:** {s['session']}\n")
        md.append(f"- **R:R esperado:** {s['rr']}\n")
        md.append(f"- **Win-rate esperado:** {s['expected_winrate']}\n")
        md.append("\n**Reglas de ejecución:**\n")
        for r in s["rules"]:
            md.append(f"- {r}\n")
        md.append("\n**Filtros obligatorios:**\n")
        for f in s["filters"]:
            md.append(f"- {f}\n")

    md.append("\n## 3. REGLAS ESTRICTAS (no negociables)\n")
    for r in STRICT_RULES:
        md.append(f"- **[{r['category']}/{r['severity'].upper()}]** {r['rule']}\n")

    md.append("\n## 4. CHECKLIST DIARIO\n\n### Pre-mercado\n")
    for c in CHECKLIST_TEMPLATE["pre_market"]:
        md.append(f"- [ ] {c['text']}\n")
    md.append("\n### Durante mercado\n")
    for c in CHECKLIST_TEMPLATE["during_market"]:
        md.append(f"- [ ] {c['text']}\n")
    md.append("\n### Post-mercado\n")
    for c in CHECKLIST_TEMPLATE["post_market"]:
        md.append(f"- [ ] {c['text']}\n")

    md.append("\n## 5. MINDSET\n")
    for p in MINDSET_PRINCIPLES:
        md.append(f"\n### {p['title']}\n{p['body']}\n")

    md.append("\n## 6. SETUP TÉCNICO (paso a paso)\n")
    for s in SETUP_GUIDE:
        md.append(f"\n### Paso {s['step']}: {s['title']}\n```bash\n")
        for cmd in s["commands"]:
            md.append(f"{cmd}\n")
        md.append("```\n")

    md.append("\n## 7. CIERRE\n")
    md.append("> Esta no es una garantía de ganar. Es un proceso para perder MENOS y dejar correr lo que funciona.\n")
    md.append("> 1% al día compuesto durante 12 meses convierte $800 en > $10,000. Pero requiere ejecutar 250 días seguidos sin saltarte una regla.\n")
    md.append("> El edge no está en la estrategia. Está en la disciplina. Empieza hoy.\n")

    return "".join(md)
