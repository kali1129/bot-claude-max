# PRD — Futures Trading Plan Dashboard ($800 Operations Center)

## Original problem statement (literal)
> "disena un plan en el que con cluade pro crearemos varios MCP, estrategias, skills y todo lo que nos favoresca para el treding de futuros con un capital de 800 dolares.
> Usaremos el Plna Pro Max de 200 dolares de claude. Una laptop con windows y WSL. MT5 con una cuenta real con 800 dolares.
> MCP de noticias, MCP de trading, Estrategias acertivas, reglas muy claras, Y cualquier otra sugerencia que puedas darme."

## Aclaraciones del usuario
- Quiere: documento Markdown + dashboard web + prompts para Claude Code que construya los MCPs en su WSL/Windows.
- AI debe decidir cada día el mejor mercado entre índices, forex, commodities, cripto futuros.
- Trading: intradía o overnight. **NUNCA** múltiples posiciones abiertas a la vez.
- Noticias: ForexFactory + APIs confiables (Finnhub/NewsAPI). NO Twitter. Correlacionar hora pub vs ahora para validar entrada.
- Experiencia: principiante con bots, intermedio manual, ha perdido miles → enfoque en disciplina/psicología.
- Cuenta real $800 en MT5.

## Tech stack
- Backend: FastAPI + Motor/MongoDB + Pydantic
- Frontend: React 19 + Tailwind + Recharts + Sonner toasts + Lucide icons
- Tipografía: Chivo (display), IBM Plex Sans (body), JetBrains Mono (data) vía Google Fonts
- Tema: dark Bloomberg-terminal (negro #0a0a0a, accent verde #10b981, ambar #f59e0b, rojo #ef4444)

## Personas
- **Trader retail con $800 reales, intermedio manual, ha perdido miles**: necesita un sistema externo que le imponga disciplina, calcule riesgo, registre trades y le dé prompts listos para que Claude Code construya los MCPs.

## Core requirements
- 1% riesgo por trade (= $8), 3% drawdown diario máx (= $24), 1 sola posición simultánea, R:R mínimo 1:2, 3 pérdidas consecutivas → STOP día.
- 4 MCPs: News (ForexFactory + NewsAPI/Finnhub), Trading (MT5 con guardas), Analysis (indicadores+estructura), Risk (guardian de cuenta).
- 6 estrategias validadas (4 intradía, 1 swing, 1 reactiva).
- 20 reglas estrictas categorizadas (MONEY, EXECUTION, TIMING, MINDSET, DISCIPLINE).
- Checklist diario interactivo (18 ítems) persistido en Mongo.
- Calculadora de tamaño de posición con presets por activo.
- Diario de trades con stats (win-rate, expectancy, equity curve).
- Guía de setup en 9 pasos.
- 6 principios de mindset.
- Plan completo descargable como Markdown.

## What's been implemented (2026-01)
- ✅ Backend: 11 endpoints REST funcionando 100% (testing agent)
  - `/api/plan/data` y `/api/plan/markdown` (contenido del plan)
  - `/api/journal` CRUD + `/api/journal/stats` (stats agregadas)
  - `/api/checklist/{date}` GET + POST upsert
  - `/api/risk/calc` con validaciones y warnings
- ✅ Frontend dashboard 9 secciones con sidebar navegable, topbar live (UTC, equity, P&L, status), ticker animado de reglas
- ✅ MCPs section con prompts copy-paste para Claude Code (4 MCPs)
- ✅ Calculadora de riesgo con 5 presets (EURUSD, USDJPY, XAUUSD, NAS100, BTCUSD)
- ✅ Trade journal con form, tabla, stats y equity curve (recharts)
- ✅ Checklist diario interactivo persistente
- ✅ Setup guide 9 pasos
- ✅ Mindset section
- ✅ Download del plan completo como `.md`
- ✅ Tema Bloomberg-terminal con tipografías Chivo/IBM Plex Sans/JetBrains Mono
- ✅ data-testid en todos los elementos interactivos

## Tests
- Iteration 1: backend 100% pass · frontend 100% pass · 0 console errors · todas las funcionalidades end-to-end OK.

## Backlog / Next features
- **P1**: Integrar realmente con MCP de Claude Desktop (deep-link o auto-instalador)
- **P1**: Agregar gráfico de win-rate por estrategia para identificar cuál funciona mejor
- **P1**: Auto-import de trades desde MT5 history (export CSV → parser)
- **P2**: Auth de usuarios (multi-tenant) con Emergent Google Auth si quiere compartir
- **P2**: Migrar `@app.on_event` a lifespan handler (FastAPI moderno)
- **P2**: Reemplazar `window.confirm` por AlertDialog (shadcn) para mantener look
- **P2**: Notificaciones browser cuando hay noticia HIGH-impact
- **P3**: Mobile-optimized layout (sidebar colapsable)
- **P3**: Modo "demo vs real" toggle (separar journals)

## Files
- `/app/backend/server.py` — FastAPI con 11 endpoints
- `/app/backend/plan_content.py` — todo el contenido estático (MCPs, strategies, rules, checklist, mindset, setup, build_markdown)
- `/app/frontend/src/Dashboard.jsx` — orquestador
- `/app/frontend/src/components/{Sidebar,TopBar,Footer}.jsx`
- `/app/frontend/src/sections/{Overview,MCPArchitecture,Strategies,Rules,Checklist,RiskCalculator,TradeJournal,SetupGuide,Mindset}.jsx`
- `/app/backend/tests/backend_test.py` — 15 tests pytest creados por testing agent
