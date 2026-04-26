# 05 — Dashboard Web (Operations Center)

> El dashboard web que estás viendo. NO es el MCP, es el **panel de control humano**: el lugar donde lees el plan, ejecutas el checklist diario, calculas lotajes manualmente, registras trades y revisas tu equity curve. Es tu copiloto consciente.

## Propósito

Los 4 MCPs viven dentro de Claude Desktop. Pero tú necesitas un lugar fuera de Claude para:

1. **Leer el plan** (estrategias, reglas, mindset) sin abrir Claude.
2. **Hacer el checklist diario** con persistencia (no se borra al cerrar).
3. **Calcular lotajes** rápidamente desde el browser, sin invocar Claude.
4. **Registrar trades** manualmente con campos estructurados.
5. **Ver equity curve** y stats agregadas (win-rate, expectancy).
6. **Descargar el plan completo** en Markdown para llevártelo offline.

Es complementario a los MCPs, no los reemplaza.

---

## Stack técnico

| Capa | Tecnología | Por qué |
|---|---|---|
| Frontend | React 19 + Tailwind | DX rápido, componentes Radix-UI |
| Charts | Recharts | declarativo, sano para series temporales |
| Toasts | Sonner | minimal, dark-friendly |
| Iconos | Lucide React | tree-shakeable, consistentes |
| Fonts | Chivo + IBM Plex Sans + JetBrains Mono | Bloomberg-terminal aesthetic |
| Backend | FastAPI + Motor (async MongoDB) | rápido, async, Pydantic |
| DB | MongoDB | flexibilidad para journal/checklist sin migraciones |
| Routing | React Router 7 | single-page con anchor scroll |

---

## Estructura del repo

```
/app/
├── backend/
│   ├── server.py              # 11 endpoints REST bajo /api
│   ├── plan_content.py        # contenido estático del plan (single source of truth)
│   ├── requirements.txt
│   ├── .env                   # MONGO_URL, DB_NAME
│   └── tests/
│       └── backend_test.py
│
├── frontend/
│   ├── src/
│   │   ├── App.js             # router + toaster
│   │   ├── Dashboard.jsx      # orquestador principal
│   │   ├── components/
│   │   │   ├── Sidebar.jsx    # nav lateral 240px
│   │   │   ├── TopBar.jsx     # equity, P&L, status, ticker
│   │   │   └── Footer.jsx
│   │   ├── sections/
│   │   │   ├── Overview.jsx
│   │   │   ├── MCPArchitecture.jsx
│   │   │   ├── Strategies.jsx
│   │   │   ├── Rules.jsx
│   │   │   ├── Checklist.jsx
│   │   │   ├── RiskCalculator.jsx
│   │   │   ├── TradeJournal.jsx
│   │   │   ├── SetupGuide.jsx
│   │   │   └── Mindset.jsx
│   │   ├── index.css          # CSS variables + utilidades
│   │   └── App.css
│   ├── public/index.html      # meta + Google Fonts
│   ├── package.json
│   └── tailwind.config.js
│
├── docs/                      # ← ESTOS READMEs
└── memory/PRD.md
```

---

## Endpoints REST (`/api`)

| Verb | Path | Descripción |
|---|---|---|
| GET | `/api/` | Health check (`{message, capital}`) |
| GET | `/api/plan/data` | Todo el plan estructurado (config, mcps, strategies, rules, checklist, mindset, setup_guide) |
| GET | `/api/plan/markdown` | Plan completo como `.md` (descarga) |
| GET | `/api/docs` | Lista de READMEs disponibles |
| GET | `/api/docs/{name}` | Devuelve un README específico |
| GET | `/api/journal` | Lista de trades (sin `_id` Mongo) |
| POST | `/api/journal` | Crea trade |
| DELETE | `/api/journal/{id}` | Borra trade |
| GET | `/api/journal/stats` | Stats agregadas (win-rate, expectancy, equity_curve, today) |
| GET | `/api/checklist/{date}` | Estado de checklist para fecha |
| POST | `/api/checklist` | Upsert checklist por fecha |
| POST | `/api/risk/calc` | Calcula lotaje |

### Ejemplo: crear trade
```bash
curl -X POST $API/api/journal -H "Content-Type: application/json" -d '{
  "date": "2026-01-15",
  "symbol": "EURUSD",
  "side": "buy",
  "strategy": "EMA 200 Pullback",
  "entry": 1.0850, "exit": 1.0890,
  "sl": 1.0830, "tp": 1.0890,
  "lots": 0.03, "pnl_usd": 12.0, "r_multiple": 2.0,
  "status": "closed-win",
  "notes": "Setup limpio en H4 EMA200. Entrada en pullback."
}'
```

### Ejemplo: calc riesgo
```bash
curl -X POST $API/api/risk/calc -H "Content-Type: application/json" -d '{
  "balance": 800, "risk_pct": 1,
  "entry": 1.0850, "stop_loss": 1.0830,
  "pip_value": 10, "pip_size": 0.0001,
  "lot_step": 0.01, "min_lot": 0.01, "max_lot": 0.5
}'
# → {"lots": 0.03, "risk_dollars": 6.00, "risk_pct_actual": 0.75, ...}
```

---

## Modelos Pydantic (backend)

```python
class TradeEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: str  # YYYY-MM-DD
    symbol: str
    side: Literal["buy", "sell"]
    strategy: str
    entry: float
    exit: Optional[float] = None
    sl: float
    tp: Optional[float] = None
    lots: float
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    status: Literal["open", "closed-win", "closed-loss", "closed-be"] = "open"
    notes: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class ChecklistState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: str
    checked_ids: List[str] = []
    updated_at: str

class RiskCalcInput(BaseModel):
    balance: float
    risk_pct: float
    entry: float
    stop_loss: float
    pip_value: float = 10.0
    pip_size: float = 0.0001
    lot_step: float = 0.01
    min_lot: float = 0.01
    max_lot: float = 0.5
```

---

## Diseño visual (system)

### Paleta
| Token | Hex | Uso |
|---|---|---|
| `--bg` | `#0a0a0a` | fondo página |
| `--surface` | `#121214` | paneles |
| `--surface-2` | `#18181b` | hover paneles |
| `--border` | `#27272a` | bordes 1px |
| `--text` | `#f4f4f5` | texto primario |
| `--text-dim` | `#a1a1aa` | texto secundario |
| `--green` | `#10b981` | win, accent positivo |
| `--red` | `#ef4444` | loss, danger |
| `--amber` | `#f59e0b` | warning |
| `--blue` | `#3b82f6` | info |

### Tipografía
- **Display (Chivo)**: titulares grandes, font-black, tracking-tight
- **Body (IBM Plex Sans)**: párrafos
- **Mono (JetBrains Mono)**: TODOS los datos numéricos, kickers, code

### Componentes clave
- `.panel` — surface + border 1px, sin border-radius
- `.kicker` — etiquetas tipo terminal `// LIVE`, uppercase, tracking 0.22em
- `.btn-sharp` — botón cuadrado, mono, uppercase
- `.input-sharp` — input dark sin radius
- `.codeblock` — pre con border, font mono 12px
- `.stripes-danger` / `.stripes-warn` — patrones diagonales para callouts

### Layout
- Sidebar fija 240px izquierda
- Topbar sticky con stats horizontales + ticker animado
- Contenido scroll vertical, secciones con `scroll-margin-top: 80px`

---

## Comandos de desarrollo

### Backend
```bash
cd /app/backend
pip install -r requirements.txt
# El servidor lo gestiona supervisor en /app, no usar uvicorn manual:
sudo supervisorctl restart backend
sudo supervisorctl status backend
tail -f /var/log/supervisor/backend.*.log
```

### Frontend
```bash
cd /app/frontend
yarn install
# Hot reload activo:
sudo supervisorctl restart frontend
```

### Tests
```bash
# Backend tests
pytest /app/backend/tests/backend_test.py -v
# Frontend lint
cd /app/frontend && yarn lint  # (configurado en eslint.config.mjs)
```

---

## Variables de entorno

### Backend (`/app/backend/.env`)
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=test_database
CORS_ORIGINS=*
```

### Frontend (`/app/frontend/.env`)
```
REACT_APP_BACKEND_URL=https://<tu-app>.preview.emergentagent.com
WDS_SOCKET_PORT=443
ENABLE_HEALTH_CHECK=false
```

⚠️ **NO modifiques** `MONGO_URL`, `DB_NAME` ni `REACT_APP_BACKEND_URL` — están preconfigurados.

---

## Cómo se conecta el dashboard con los MCPs

**No se conectan directamente.** Son sistemas independientes:

```
Dashboard web              MCPs en Claude Desktop
─────────────              ─────────────────────
- Lees plan      ←→  copy-paste prompts → Claude Code construye MCPs
- Marcas checklist
- Calculas lotaje  ←   (mismo cálculo en risk-mcp)
- Registras trade   ←  (después de cerrar en MT5)
- Ves equity curve
```

Trade-off deliberado: si el dashboard cae, los MCPs siguen funcionando. Si los MCPs se desconectan, el dashboard sigue siendo útil para journal y plan. Ambos son fuentes-de-verdad **distintas**.

> 💡 Versión 2 podría auto-sincronizar trades desde MT5 → dashboard vía polling de un endpoint `POST /api/journal/import-mt5-csv`. Está en backlog.

---

## Secciones del dashboard (deep dive)

### 00 · Overview
Hero con titular, 4 metric cards (Capital, Equity, Win Rate, Expectancy) y risk model strip. Pull data de `/api/plan/data` + `/api/journal/stats`.

### 01 · MCP Stack
4 cards de MCPs. Cada una con:
- Tools list
- Env keys badges
- Copy Prompt button (copia al clipboard el prompt completo)
- Ver/Ocultar prompt (codeblock expandible)

Más diagrama ASCII del flow.

### 02 · Strategies
6 cards de estrategias en grid 1/2/3 cols responsive. Cada card: name + type, metrics (R:R, win-rate, sesión), best_for, sesión completa, reglas numeradas, filtros obligatorios.

### 03 · Strict Rules
20 reglas agrupadas por categoría (MONEY, EXECUTION, TIMING, MINDSET, DISCIPLINE). Severidad coloreada (critical = rojo + stripes, high = amber + stripes, medium = blue).

### 04 · Daily Checklist
3 paneles (pre-market 7 items, durante 6 items, post 5 items). Click en checkbox → toggle + persist en `/api/checklist`. Estado persiste entre sesiones, se resetea al cambiar día. Progress bar arriba.

### 05 · Risk Calc
Formulario con 5 presets de activos (EURUSD, USDJPY, XAUUSD, NAS100, BTCUSD) que setean pip_size + pip_value. Inputs: balance, risk %, entry, SL. Botón calcular → llama `/api/risk/calc` → muestra lotaje grande, riesgo $, riesgo % real, SL distance, SL pips, warnings.

### 06 · Trade Journal
- Stats strip (total trades, win rate, expectancy, total P&L)
- Form expandible con todos los campos del modelo TradeEntry
- Equity curve con Recharts (`stepAfter` line, dots verdes, reference line en $800)
- Tabla con filas hoverable, status badges colored, botón delete por fila

### 07 · Setup Guide
9 steps con número grande, título y bloque de comandos `bash`. Más checklist de migración a real con stripes-warn.

### 08 · Mindset
6 principios numerados en grid 2-cols. Cierre con frase grande "El edge no está en la estrategia. Está en la disciplina."

---

## Accesibilidad y testabilidad

- Todos los elementos interactivos llevan `data-testid` (kebab-case, role-based)
- Contraste AAA en texto principal (text vs bg = 15.4:1)
- Focus rings visibles (`outline-none` solo en input cuando se reemplaza con border-color)
- Sin animaciones excesivas (motion: minimalist según design guidelines)

---

## Despliegue

Está pensado para correr en Emergent Cloud (Kubernetes managed):
- Frontend en port 3000
- Backend en port 8001
- MongoDB local
- Hot reload activo
- URL pública: definida en `REACT_APP_BACKEND_URL`

Para self-host:
1. Mongo: docker `mongo:7`
2. Backend: `uvicorn server:app --host 0.0.0.0 --port 8001`
3. Frontend: `yarn build && serve -s build -l 3000`
4. Reverse proxy (nginx) con rewrite `/api/* → :8001` y `/* → :3000`

---

## Roadmap (lo que NO está pero podría)

| Prio | Feature | Notas |
|---|---|---|
| P1 | Auto-import MT5 history (CSV upload) | Endpoint `POST /api/journal/import` |
| P1 | Gráfico win-rate por estrategia | Nueva tarjeta en journal |
| P1 | Daily Briefing (mañana) | LLM mini-resumen de noticias + sugerencia activos |
| P2 | Auth multi-usuario (Emergent Google) | Para compartir con socio o coach |
| P2 | Notificaciones push noticias HIGH | PWA service worker |
| P2 | Modo "demo vs real" toggle | Journals separados |
| P3 | Mobile-first sidebar collapsable | Para review desde celular |
| P3 | Backtest histórico | Sube CSV, score_setup retroactivo |

---

## Troubleshooting

| Problema | Diagnóstico | Fix |
|---|---|---|
| Dashboard no carga | Frontend env mal | Verifica `REACT_APP_BACKEND_URL` en `/app/frontend/.env` |
| `/api/*` devuelve 404 | Backend caído | `sudo supervisorctl status backend` + tail logs |
| Mongo connection refused | Mongo caído | `sudo supervisorctl status mongodb` |
| Equity curve vacía | sin trades cerrados | Crea ≥1 trade con status closed-* |
| Checklist no persiste | Mongo sin permisos | Revisa logs backend |

---

## Validación

- [ ] `/api/plan/data` devuelve 4 mcps + 6 strategies + 20 rules
- [ ] Crear trade → aparece en tabla y stats se actualizan
- [ ] Checklist persiste tras reload
- [ ] Risk calc con preset XAUUSD funciona
- [ ] Equity curve renderiza con 2+ trades
- [ ] Botón "Download .md" descarga archivo válido
- [ ] Sin errores de console
