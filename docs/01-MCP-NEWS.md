# 01 — MCP de Noticias & Calendario Económico

> Servidor MCP en Python que recolecta calendario económico (ForexFactory) + noticias de fuentes confiables (Reuters/Bloomberg/FT vía Finnhub & NewsAPI). Su trabajo es responder a una sola pregunta: **"¿es seguro operar este símbolo AHORA mismo, o hay info que invalida la operación?"**

## Propósito

Operar contra una noticia de alto impacto que acaba de salir es la forma más rápida de morir. Este MCP existe para evitar dos errores:

1. **Operar 30 min antes/después de una noticia HIGH-impact** (NFP, CPI, FOMC, etc.) — los stops se barren por la volatilidad sintética.
2. **Operar tarde una noticia ya descontada** — entrar a las 14:30 en un movimiento que arrancó a las 14:00 te pone en el peor punto del retorno.

El MCP correlaciona la **hora de publicación** con la **hora actual** y clasifica el símbolo como `tradeable | tradeable-with-caution | NOT-tradeable`.

---

## Arquitectura interna

```
                ┌────────────────────────┐
   Claude  ──→  │   news-mcp (Python)    │
                │                        │
                │  ┌──────────────────┐  │
                │  │ ForexFactory     │  │  ← scraping HTML
                │  │ scraper          │  │
                │  └──────────────────┘  │
                │  ┌──────────────────┐  │
                │  │ Finnhub client   │  │  ← API REST
                │  │ (preferred)      │  │
                │  └──────────────────┘  │
                │  ┌──────────────────┐  │
                │  │ NewsAPI client   │  │  ← API REST (fallback)
                │  │ (fallback)       │  │
                │  └──────────────────┘  │
                │  ┌──────────────────┐  │
                │  │ Symbol → currency│  │  ← mapping interno
                │  │ mapper           │  │
                │  └──────────────────┘  │
                │  ┌──────────────────┐  │
                │  │ Decision engine  │  │  ← reglas de blackout
                │  │ (is_tradeable)   │  │
                │  └──────────────────┘  │
                └────────────────────────┘
```

### Decision engine (reglas de blackout)

| Condición | Resultado |
|---|---|
| Hay evento HIGH-impact en ±30 min de la divisa del símbolo | `tradeable: false` (BLACKOUT) |
| Noticia <5 min con `relevance_score > 70` | `tradeable: false` (movimiento fresco) |
| Noticia 5-30 min con `relevance_score > 70` | `tradeable: true, caution: "fresh news"` |
| Noticia 30-90 min con `relevance_score > 70` | `tradeable: true, caution: "fade-only"` |
| Sin nada relevante | `tradeable: true, normal: true` |

---

## Estructura de archivos

```
news-mcp/
├── server.py              # FastMCP server + 4 tools
├── requirements.txt
├── .env                   # FINNHUB_API_KEY, NEWSAPI_KEY
├── .env.example
├── lib/
│   ├── ff_calendar.py     # ForexFactory scraper
│   ├── finnhub_client.py
│   ├── newsapi_client.py
│   ├── symbol_map.py      # EURUSD → [EUR, USD]
│   └── relevance.py       # heurística de score
└── tests/
    └── test_decision.py
```

## Dependencies (`requirements.txt`)

```
mcp>=1.0.0
httpx>=0.27.0
beautifulsoup4>=4.12.0
python-dateutil>=2.9.0
pytz>=2024.1
python-dotenv>=1.0.1
pydantic>=2.6
```

## Variables de entorno

| Var | Obligatoria | Cómo obtener |
|---|---|---|
| `FINNHUB_API_KEY` | sí (preferred) | https://finnhub.io · plan gratuito 60 calls/min |
| `NEWSAPI_KEY` | sí (fallback) | https://newsapi.org · plan gratuito 100 calls/día |
| `FF_USER_AGENT` | no | UA realista para no ser bloqueado por ForexFactory |
| `LOG_LEVEL` | no | `INFO` (default) |

⚠️ **NO uses Twitter/X** ni redes sociales. Confiabilidad insuficiente para tomar decisiones con dinero real.

---

## Tools expuestas (4)

### 1. `get_economic_calendar(date, impact)`

Devuelve eventos del día desde ForexFactory.

**Args:**
- `date` (str) — `"today"` | `"tomorrow"` | `"YYYY-MM-DD"` (default `today`)
- `impact` (str) — `"high"` | `"medium"` | `"low"` | `"all"` (default `high`)

**Returns:**
```json
{
  "events": [
    {
      "time_utc": "2026-01-15T13:30:00Z",
      "currency": "USD",
      "event": "Core CPI m/m",
      "impact": "high",
      "actual": null,
      "forecast": "0.3%",
      "previous": "0.3%",
      "minutes_until": 47
    },
    ...
  ],
  "count": 3,
  "source": "forexfactory.com"
}
```

**Implementación clave:**
```python
async def fetch_ff_calendar(target_date: date) -> list:
    url = f"https://www.forexfactory.com/calendar?day={target_date.strftime('%b%d.%Y').lower()}"
    headers = {"User-Agent": os.getenv("FF_USER_AGENT", DEFAULT_UA)}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers=headers)
        r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.select("tr.calendar__row")
    events = []
    for row in rows:
        impact_cell = row.select_one(".calendar__impact span")
        if not impact_cell: continue
        title = impact_cell.get("title", "")
        if "High Impact" in title:
            impact = "high"
        elif "Medium Impact" in title:
            impact = "medium"
        elif "Low Impact" in title:
            impact = "low"
        else: continue
        # … parse time, currency, event, actual, forecast, previous
    return events
```

---

### 2. `get_news(query, since_minutes, max_items)`

Devuelve noticias recientes filtradas por **fuentes confiables únicamente**.

**Args:**
- `query` (str) — símbolo MT5 o tema (`"EURUSD"`, `"NAS100"`, `"FOMC"`)
- `since_minutes` (int) — antigüedad máxima (default `60`)
- `max_items` (int) — default `10`

**Returns:**
```json
{
  "news": [
    {
      "title": "Fed signals pause as inflation cools",
      "source": "reuters.com",
      "url": "https://...",
      "published_at_utc": "2026-01-15T12:45:00Z",
      "summary": "...",
      "age_minutes": 23,
      "relevance_score": 82
    }
  ],
  "fuentes_permitidas": [
    "reuters.com", "bloomberg.com", "ft.com",
    "wsj.com", "cnbc.com", "marketwatch.com",
    "investing.com", "forexlive.com"
  ]
}
```

**Filtro de fuentes (whitelist):**
```python
ALLOWED_SOURCES = {
    "reuters.com", "bloomberg.com", "ft.com",
    "wsj.com", "cnbc.com", "marketwatch.com",
    "investing.com", "forexlive.com"
}
```

Cualquier otra fuente se descarta.

---

### 3. `is_tradeable_now(symbol)`

La pregunta-clave del MCP. Devuelve veredicto.

**Args:**
- `symbol` (str) — `"EURUSD"`, `"XAUUSD"`, `"NAS100"`, `"BTCUSD"`, etc.

**Returns:**
```json
{
  "symbol": "EURUSD",
  "tradeable": false,
  "reason": "High-impact CPI USD en 18 min — BLACKOUT",
  "blocker_event": {
    "currency": "USD",
    "event": "Core CPI m/m",
    "minutes_until": 18,
    "impact": "high"
  },
  "fresh_news": [],
  "checked_at_utc": "2026-01-15T13:12:30Z"
}
```

**Símbolo → divisas afectadas:**
```python
SYMBOL_MAP = {
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "XAUUSD": ["USD"],            # oro
    "NAS100": ["USD"],            # índices US
    "US30":   ["USD"],
    "DAX":    ["EUR"],
    "BTCUSD": ["USD"],            # cripto
}
```

**Lógica:**
```python
def is_tradeable(symbol: str) -> dict:
    currencies = SYMBOL_MAP.get(symbol, [])
    cal = get_calendar(date="today", impact="high")
    now = datetime.now(timezone.utc)

    # Regla 1: blackout ±30min noticia HIGH
    for event in cal["events"]:
        if event["currency"] not in currencies: continue
        delta = abs((event["time_utc"] - now).total_seconds() / 60)
        if delta <= 30:
            return {
                "tradeable": False,
                "reason": f"High-impact {event['event']} {event['currency']} en {int(delta)} min",
                "blocker_event": event,
            }

    # Regla 2: noticia fresca con relevance alto
    news = get_news(query=symbol, since_minutes=90)
    fresh = [n for n in news if n["age_minutes"] < 5 and n["relevance_score"] >= 70]
    if fresh:
        return {"tradeable": False, "reason": "Movimiento fresco — espera retest", "fresh_news": fresh}

    medium = [n for n in news if 5 <= n["age_minutes"] < 30 and n["relevance_score"] >= 70]
    if medium:
        return {"tradeable": True, "caution": "fresh-news", "fresh_news": medium}

    return {"tradeable": True, "normal": True}
```

---

### 4. `news_relevance_score(headline, symbol)`

Heurística simple por keywords (0–100).

**Args:** `headline: str`, `symbol: str`
**Returns:** `{score: int, matched_keywords: list}`

```python
KEYWORDS = {
    "USD": [("FOMC", 30), ("Fed", 25), ("CPI", 25), ("NFP", 30),
            ("powell", 20), ("inflation", 15), ("jobs", 15)],
    "EUR": [("ECB", 30), ("Lagarde", 20), ("eurozone", 15)],
    "GBP": [("BoE", 30), ("Bailey", 20)],
    # …
}
```

---

## Server skeleton (`server.py`)

```python
"""news-mcp v1.0.0 — Reliable news + economic calendar for futures trading."""
import os
import sys
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from lib.ff_calendar import fetch_ff_calendar
from lib.finnhub_client import FinnhubClient
from lib.newsapi_client import NewsAPIClient
from lib.symbol_map import SYMBOL_MAP
from lib.relevance import score_headline

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), stream=sys.stderr)
log = logging.getLogger("news-mcp")

mcp = FastMCP("news")
finnhub = FinnhubClient(os.environ["FINNHUB_API_KEY"])
newsapi = NewsAPIClient(os.environ["NEWSAPI_KEY"])


@mcp.tool()
async def get_economic_calendar(date: str = "today", impact: str = "high") -> dict:
    """ForexFactory economic calendar."""
    try:
        events = await fetch_ff_calendar(_parse_date(date))
        if impact != "all":
            events = [e for e in events if e["impact"] == impact]
        return {"events": events, "count": len(events), "source": "forexfactory.com"}
    except Exception as e:
        log.exception("calendar failed")
        return {"events": [], "error": str(e)}


@mcp.tool()
async def get_news(query: str, since_minutes: int = 60, max_items: int = 10) -> dict:
    try:
        items = await finnhub.search(query, since_minutes, max_items)
        if not items:
            items = await newsapi.search(query, since_minutes, max_items)
        items = [i for i in items if _is_allowed_source(i["source"])]
        for it in items:
            it["relevance_score"] = score_headline(it["title"], query)
            it["age_minutes"] = _age_minutes(it["published_at_utc"])
        return {"news": items[:max_items]}
    except Exception as e:
        log.exception("news failed")
        return {"news": [], "error": str(e)}


@mcp.tool()
async def is_tradeable_now(symbol: str) -> dict:
    # … (lógica completa de arriba)
    ...


@mcp.tool()
def news_relevance_score(headline: str, symbol: str) -> dict:
    return score_headline(headline, symbol)


if __name__ == "__main__":
    mcp.run()
```

---

## Configuración Claude Desktop

`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "news": {
      "command": "python",
      "args": ["C:\\Users\\TU_USUARIO\\mcp\\news-mcp\\server.py"],
      "env": {
        "FINNHUB_API_KEY": "ckxxxxxxxxxx",
        "NEWSAPI_KEY": "xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

Reinicia Claude Desktop después de editar.

---

## Cómo construirlo (prompt para Claude Code)

> El prompt completo está en el dashboard → MCP Stack → MCP_01 → "Copy Prompt".

Te recomiendo **construir y testear este MCP primero, en aislamiento**, antes de los demás. Es el más simple y te enseña el patrón.

---

## Testing manual

Una vez configurado, en Claude Desktop:

```
Tú: "Trae el calendario económico de hoy con impacto alto"

Claude: Llamando news.get_economic_calendar(date="today", impact="high")…
        Hay 2 eventos HIGH:
        - 13:30 UTC · USD · Core CPI m/m · forecast 0.3%
        - 19:00 UTC · USD · FOMC Statement
        ...

Tú: "¿Es seguro operar EURUSD ahora?"

Claude: news.is_tradeable_now(symbol="EURUSD")
        → tradeable=false, blackout: CPI en 18 min.
        Espera al menos hasta 14:00 UTC, idealmente 14:15 UTC para tradear el retest.
```

## Edge cases / troubleshooting

| Problema | Causa probable | Fix |
|---|---|---|
| ForexFactory devuelve HTML vacío | Te bloquearon por UA | Cambia `FF_USER_AGENT` a uno realista, baja frecuencia |
| Finnhub rate-limit (429) | >60 calls/min | Cachea calendario por 15min |
| NewsAPI `apiKeyMissing` | `.env` no se cargó | Verifica que Claude Desktop pasa `env` correctamente |
| `is_tradeable_now` siempre `true` | Symbol map no incluye tu símbolo | Agrégalo a `SYMBOL_MAP` |
| Tiempos UTC desfasados | TZ mal calculado | Usa `pytz` y normaliza todo a UTC en parser |

---

## Checklist de validación

- [ ] `get_economic_calendar()` devuelve ≥1 evento en día de NFP/CPI
- [ ] `get_news("EURUSD")` filtra solo fuentes whitelisted
- [ ] `is_tradeable_now("EURUSD")` → false 30 min antes de CPI
- [ ] Funciona offline-degraded: si Finnhub falla, NewsAPI cubre
- [ ] Logs van a stderr (no contaminan stdout MCP)
- [ ] `.env` no está en git (añade a `.gitignore`)
