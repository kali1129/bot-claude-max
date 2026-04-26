# 00 — Arquitectura General

> Plan operativo de trading de futuros con **Claude Pro Max + 4 MCPs custom + MetaTrader 5** sobre Windows/WSL. Capital real $800 USD.

## TL;DR

```
┌──────────────────┐
│  Claude Pro Max  │   ← tú das instrucciones en lenguaje natural
└────────┬─────────┘
         │ MCP protocol (stdio)
         │
   ┌─────┼──────┬───────────┬──────────┐
   ▼     ▼      ▼           ▼          ▼
 news  analysis trading    risk    (dashboard web)
  │      │       │          │
  ▼      ▼       ▼          ▼
 ForexFactory   MT5 nativo  state.json
 NewsAPI/Finnhub Windows     drawdown lock
```

| Componente | Lenguaje | Corre en | Archivo principal |
|---|---|---|---|
| Claude Desktop | — | Windows | (instalado) |
| **MCP news** | Python | WSL o Windows | `news-mcp/server.py` |
| **MCP trading** | Python | **Windows nativo** (MT5 sólo Win) | `trading-mt5-mcp/server.py` |
| **MCP analysis** | Python | WSL o Windows | `analysis-mcp/server.py` |
| **MCP risk** | Python | WSL o Windows | `risk-mcp/server.py` |
| Dashboard web | React+FastAPI | local o cloud | (este repo) |
| MetaTrader 5 | — | **Windows nativo** | (instalado por broker) |

---

## ¿Por qué esta arquitectura?

### Separación por responsabilidad (Single Responsibility)
Cada MCP hace UNA sola cosa y la hace bien:

- **news** → ¿hay info que invalida operar ahora?
- **analysis** → ¿el setup es A+ (score ≥ 70)?
- **trading** → ¿podemos enviar la orden a MT5 con sus guardas?
- **risk** → ¿la cuenta está sana, podemos seguir tradeando hoy?

Si los mezcláramos en un solo MCP gigante, sería frágil, difícil de testear y un fallo en cualquier parte tumbaría todo.

### MCP como protocolo estándar
[Model Context Protocol](https://modelcontextprotocol.io) (Anthropic, 2024) permite que Claude llame funciones Python locales con tipos seguros y descubrimiento automático. Una vez que Claude conoce los 4 MCPs, puede orquestarlos en lenguaje natural:

> *"Claude, dame estado de cuenta, mira si hay noticias en EURUSD, analiza M15 y si el setup vale, calcula el lotaje y envía la orden con SL en 1.0830 y TP en 1.0890"*

→ Claude llama 7 tools en orden, decide en cada paso, y reporta.

### Por qué `trading-mcp` corre en Windows nativo
La librería `MetaTrader5` de Python **sólo existe para Windows** (depende de DLLs del terminal MT5). Por eso ese MCP único corre con el `python.exe` de Windows, no con el de WSL. Los otros 3 pueden correr donde sea.

---

## Flujo típico de un trade (orden de llamadas)

```python
# Lo que Claude hace por dentro cuando le pides "valida y ejecuta setup en EURUSD"

# 1. Guardian de cuenta
risk.daily_status()
# → {dd_pct: -0.5, trades_count: 1, can_trade: true}

# 2. Validar contexto noticias
news.is_tradeable_now("EURUSD")
# → {tradeable: true, normal: true}

# 3. Traer datos de mercado
ohlcv_h4 = trading.get_rates("EURUSD", "H4", 200)
ohlcv_m15 = trading.get_rates("EURUSD", "M15", 200)

# 4. Análisis técnico
mtf = analysis.mtf_bias(ohlcv_h4, ohlcv_m15)
# → {aligned: true, side: "buy"}

setup = analysis.score_setup(ohlcv_m15, side="buy", entry=1.0850, sl=1.0830, tp=1.0890)
# → {score: 78, recommendation: "TAKE"}

# 5. Tamaño de posición
sizing = risk.calc_position_size(balance=800, risk_pct=1, entry=1.0850, sl=1.0830, ...)
# → {lots: 0.03, risk_dollars: 6.00}

# 6. Ejecución (con guardas internas)
order = trading.place_order("EURUSD", "buy", 0.03, sl=1.0830, tp=1.0890, comment="MTF+OB")
# → {ok: true, ticket: 123456789}

# 7. Registrar en risk-mcp para drawdown tracking
risk.register_trade(profit=0, r_multiple=0, symbol="EURUSD", side="buy")
```

---

## Estructura de carpetas en tu máquina

```
C:\Users\<tu_usuario>\mcp\
│
├── news-mcp\
│   ├── server.py
│   ├── requirements.txt
│   ├── .env
│   └── README.md          ← (este 01-MCP-NEWS.md)
│
├── trading-mt5-mcp\
│   ├── server.py
│   ├── requirements.txt
│   ├── .env
│   └── README.md          ← (este 02-MCP-TRADING.md)
│
├── analysis-mcp\
│   ├── server.py
│   ├── requirements.txt
│   └── README.md          ← (este 03-MCP-ANALYSIS.md)
│
├── risk-mcp\
│   ├── server.py
│   ├── requirements.txt
│   ├── state.json         ← persiste entre runs
│   └── README.md          ← (este 04-MCP-RISK.md)
│
└── logs\
    ├── orders.jsonl       ← log de cada place_order intent
    └── deals.jsonl        ← histórico de deals cerrados
```

Y separadamente:
```
C:\Users\<tu_usuario>\AppData\Roaming\Claude\
└── claude_desktop_config.json  ← bloque mcpServers con los 4
```

---

## Convenciones globales

### Variables de entorno
Cada MCP tiene su propio `.env` (no se comparten). Esto los hace movibles entre máquinas sin filtrar credenciales cruzadas.

### Logging
- **stderr** para logs (stdout está reservado para el protocolo MCP).
- Formato: JSON Lines en `~/mcp/logs/<server-name>.jsonl`.
- Rotación: lo dejamos en manos de logrotate / archivo nuevo por mes.

### Manejo de errores
Cada tool debe **fallar suavemente**: devolver `{ok: false, reason: "..."}` en vez de raise. Claude entonces explica al usuario qué pasó y propone alternativa.

### Timeouts
Toda llamada HTTP externa: timeout 10s. Toda llamada MT5: timeout 5s. Si revienta, devolvemos error structured.

### Versionado
Cada MCP tiene su `__version__` en el header de `server.py`. Lo reportamos como tool `health()` para diagnóstico.

---

## Documentos en este pack

| Doc | Qué contiene |
|---|---|
| **00-OVERVIEW.md** | (este) — vista general |
| **01-MCP-NEWS.md** | Guía completa del MCP de Noticias |
| **02-MCP-TRADING.md** | Guía completa del MCP de Trading (MT5) |
| **03-MCP-ANALYSIS.md** | Guía completa del MCP de Análisis Técnico |
| **04-MCP-RISK.md** | Guía completa del MCP Guardian (Risk) |
| **05-DASHBOARD.md** | El dashboard web que estás viendo |
| **06-SETUP-WSL-MT5-CLAUDE.md** | Setup completo paso a paso |

---

## Disclaimer

Este sistema **no es un consejo financiero** ni garantiza retornos. Es un marco de disciplina. El edge real lo aporta tu ejecución consistente. La cuenta de $800 es 100% riesgo: puedes perderla completa.

> 1% diario compuesto durante 250 días convierte $800 en > $10,000. Pero también 5 violaciones de regla pueden volverla cero. Elige.
