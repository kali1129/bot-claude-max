# MIGRATION_FROM_LEGACY.md — Plan de migración desde xm-mt5-trading-platform

> Este documento es el **contrato** para descontinuar el bot antiguo
> (`C:\Users\Anderson Lora\bugbounty\xm-mt5-trading-platform`) y absorber sus
> partes valiosas en este bot nuevo (`NEW-BOT-PRO_MAX` / `bot-claude-max`).
>
> Reglas duras:
> - Antes de borrar nada se crea tarball completo en
>   `C:\Users\Anderson Lora\bugbounty\_archive\xm-mt5-trading-platform-<fecha>.tar.gz`.
> - Antes de portar nada se crea tag git `pre-legacy-migration` en este repo.
> - Cada port se adapta al blueprint: `FastMCP`, `_shared/rules`,
>   `_shared/halt`, `paper`-mode por defecto, type hints, tests.
> - Nada de `bypass_guards`, nada de relajar reglas para que algo del bot viejo
>   "encaje". Si encaja, encaja al estándar nuevo. Si no, va a `legacy/` o se
>   descarta con justificación escrita.
> - El criterio de éxito de cada port es: **tests verdes + smoke en paper**.

---

## 1. Inventario y disposición

Tabla de los 19 subsistemas de `xm-mt5-trading-platform/src/` más los activos
auxiliares (config, mql5, data, scripts).

Leyenda:
- **PORT** = se adapta al blueprint del bot nuevo y se integra.
- **PARTIAL** = solo se rescatan piezas concretas; el resto se descarta.
- **REDUNDANT** = el bot nuevo ya cubre esa función; se descarta sin port.
- **LEGACY** = se copia tal cual a `NEW-BOT-PRO_MAX/legacy/` como referencia
  no ejecutable, porque tiene valor histórico (datos reales, EAs MQL5) pero no
  encaja con el blueprint.
- **DISCARD** = no aporta nada al bot nuevo; se elimina sin reemplazo.

| # | Subsistema viejo | LOC | Disposición | Destino en bot nuevo |
|---|---|---:|---|---|
| 1 | `src/strategies/` | 892 | **PORT** | `mcp-scaffolds/analysis-mcp/lib/strategies/` (nuevo módulo) |
| 2 | `src/decision/` | 3283 | **PARTIAL** | `pretrade_gate` lógica → `analysis-mcp/lib/pretrade.py`. `coordinator.py` se descarta (Claude orquesta). |
| 3 | `src/features/` | 829 | **PORT** | `mcp-scaffolds/analysis-mcp/lib/features/` |
| 4 | `src/filters/` | 27 | **PORT** | `analysis-mcp/lib/filters.py` (session filter) |
| 5 | `src/analysis/` | 3526 | **PARTIAL** | `profile_models`, `profile_runner`, `opportunity_ranker` → `analysis-mcp/lib/profiles/`. El resto (`agent_consensus`, `agent_coordinator`, `agent_event_bus`, `agent_*`) DISCARD: era andamiaje multi-agente que Claude reemplaza. |
| 6 | `src/backtest/` | 1387 | **PORT** | `backend/lib/backtest/` + endpoint `POST /api/backtest/run` y script CLI `scripts/run_backtest.py` |
| 7 | `src/risk/` | 1503 | **PARTIAL** | `conviction_sizing`, `drawdown_guard`, `setup_memory` → `mcp-scaffolds/risk-mcp/lib/`. `kill_switch` REDUNDANT (ya hay `_shared/halt.py`). |
| 8 | `src/news/` | 1392 | **PARTIAL** | `collector`, `event_calendar`, `headline_normalizer`, `relevance_ranker`, `sentiment_guard` → `news-mcp/lib/`. `codex_news_gate` DISCARD. |
| 9 | `src/execution/` | 1900 | **PARTIAL** | `sl_tp_manager`, `trailing_stop`, `reconciliation` → `trading-mt5-mcp/lib/`. El resto REDUNDANT (ya cubierto por `place_order`). |
| 10 | `src/brokers/` | 1064 | **REDUNDANT** | `trading-mt5-mcp/lib/connection.py` ya cubre. Cherry-pick solo si aparece un edge case específico durante port. |
| 11 | `src/market_data/` | 883 | **PARTIAL** | `quality_checks` → `trading-mt5-mcp/lib/quality.py`. Resto REDUNDANT. |
| 12 | `src/mcp_mt5/` | 277 | **REDUNDANT** | `trading-mt5-mcp/server.py` ya tiene la superficie completa. |
| 13 | `src/paper/` | 750 | **REDUNDANT** | El nuevo `trading-mt5-mcp` ya tiene `paper_trades.jsonl` y modo paper. Cherry-pick `simulator.py` solo si necesitamos generar series sintéticas para backtest. |
| 14 | `src/monitoring/` | 8295 | **PARTIAL** | `quality_assessment.py`, `performance_tracker.py`, `healthcheck.py`, `audit_logger.py` → `backend/lib/monitoring/`. El resto (`alerts`, `dashboards`, `control_center_views`, `failover_audit`, `memory_layer`, `news_audit_log`, `notification_governor`, `service`, `telegram_notifier`, `telegram_operator_output`, `demo_validation`) en su mayoría DISCARD o reemplazado por `backend/server.py` y `backend/telegram_notifier.py` ya existentes. |
| 15 | `src/control/` | 3630 | **PARTIAL** | El bot de Telegram bidireccional (`local_command_router`, `local_command_models`, `local_command_center`, `local_policy_guard`) → `backend/lib/telegram_control/` + endpoint `POST /api/telegram/command`. `desired_state.py` → `backend/lib/desired_state.py`. `local_runtime.py` REDUNDANT. |
| 16 | `src/integrations/` | 13414 | **DISCARD** | Todo este módulo es andamiaje específico para gestionar slots de Codex/OpenClaw del usuario, no tiene nada que ver con trading. Cero valor para el bot nuevo. |
| 17 | `src/persistence/` | 114 | **REDUNDANT** | El bot nuevo usa MongoDB + JSONL. SQLite no se reintroduce. |
| 18 | `src/logger/` | 40 | **REDUNDANT** | El bot nuevo ya tiene logging estructurado. |
| 19 | `src/common/` | 803 | **PARTIAL** | `clock.py`, `ids.py`, `jsonl.py`, `timeframes.py`, `enums.py` (subset), `models.py` (subset Pydantic) → `mcp-scaffolds/_shared/` o `backend/lib/common/`. |
| 20 | `src/settings/` | 1932 | **PARTIAL** | `validation.py` y `startup_self_check.py` → `backend/lib/selfcheck.py`. El resto REDUNDANT (Pydantic settings ya hay). |
| 21 | `mql5/` (Experts + Files) | — | **LEGACY** | `legacy/mql5/` — `XMBridgeEA.mq5` y `XMTerminalBridge.mq5` son valiosos como referencia de cómo el bot viejo hablaba con MT5 vía file-bridge. El bot nuevo usa el paquete Python `MetaTrader5` directo, así que no se ejecutan, pero documentan el patrón. |
| 22 | `config/*.yaml` (10 archivos) | — | **PARTIAL** | `analysis-profiles.yaml`, `news.yaml`, `paper.yaml`, `live.yaml`, `backtest.yaml`, `base.yaml` → `NEW-BOT-PRO_MAX/config/legacy/` y se cherry-pickean defaults durante el port. `failover.yaml`, `openclaw-control.yaml`, `control-center.yaml`, `demo.yaml` DISCARD. |
| 23 | `data/daily_pnl_state.json` | — | **PORT** | Estado real (`+25 USD profit target reached`) → seed en `risk-mcp/state.json` con migración de schema. |
| 24 | `CLAUDE.md` (memoria de trades) | — | **PORT** | Tabla de trades reales (Apr 15–25) → seed `trades` en MongoDB del backend, vía `POST /api/journal` con `client_id = "legacy-<hash>"`. |
| 25 | `docs/*.md` (29 docs) | — | **PARTIAL** | `risk_engine.md`, `risk-policy.md`, `strategy-spec.md`, `analysis-profiles.md`, `execution-rules.md`, `news-gate.md`, `mt5_bridge.md`, `runbook.md`, `quality-assessment.md` → `legacy/docs/` como referencia. El resto DISCARD (codex/openclaw/setup específicos del entorno viejo). |
| 26 | `scripts/run_*.py` (run_backtest, run_walk_forward, run_quality_assessment, run_self_check, run_telegram_control_bot, validate_demo_operation) | — | **PARTIAL** | Reescritos minimalistamente como `NEW-BOT-PRO_MAX/scripts/run_<x>.py` que llaman a los módulos portados. |
| 27 | `scripts/*.ps1` y `*.cmd` | — | **DISCARD** | Bootstrap específico de Windows + autostart con tareas programadas; el bot nuevo se ejecuta con `uvicorn` + Claude Desktop config. Solo se preservan los atajos `🚀 Iniciar Bot XM.cmd` y `🛑 Detener Bot XM.cmd` reescritos para apuntar al bot nuevo. |
| 28 | `tests/test_*.py` (42 tests) | — | **PARTIAL** | Los tests cuyos módulos se portan, se portan también (adaptados a `pytest` del bot nuevo). El resto se descartan. |
| 29 | `logs/` | — | **DISCARD** | Salvo `audit_events.jsonl` que se mueve a `legacy/audit/` por si alguna vez hay que reconstruir histórico. `codex_enhanced_interactions.jsonl` (74 MB) se descarta. |
| 30 | `reports/backtests/`, `reports/paper/` | — | **LEGACY** | A `legacy/reports/` para tener referencia de salidas previas. |

---

## 2. Mapa final destino → origen

Para que durante el port se pueda hacer "esto vino de aquí" sin dudar:

```
NEW-BOT-PRO_MAX/
├── mcp-scaffolds/
│   ├── _shared/
│   │   └── common/         ← src/common/{clock,ids,jsonl,timeframes,enums}.py
│   ├── analysis-mcp/lib/
│   │   ├── strategies/     ← src/strategies/*.py
│   │   ├── features/       ← src/features/*.py
│   │   ├── filters.py      ← src/filters/session_filter.py
│   │   ├── pretrade.py     ← src/decision/pretrade_gate.py
│   │   └── profiles/       ← src/analysis/profile_*.py + opportunity_ranker.py
│   ├── risk-mcp/lib/
│   │   ├── conviction_sizing.py  ← src/risk/conviction_sizing.py
│   │   ├── drawdown_guard.py     ← src/risk/drawdown_guard.py
│   │   └── setup_memory.py       ← src/risk/setup_memory.py
│   ├── news-mcp/lib/
│   │   ├── collector.py          ← src/news/collector.py
│   │   ├── event_calendar.py     ← src/news/event_calendar.py
│   │   ├── headline_normalizer.py← src/news/headline_normalizer.py
│   │   ├── relevance_ranker.py   ← src/news/relevance_ranker.py
│   │   └── sentiment_guard.py    ← src/news/sentiment_guard.py
│   └── trading-mt5-mcp/lib/
│       ├── sl_tp_manager.py      ← src/execution/sl_tp_manager.py
│       ├── trailing_stop.py      ← src/execution/trailing_stop.py
│       ├── reconciliation.py     ← src/execution/reconciliation.py
│       └── quality.py            ← src/market_data/quality_checks.py
├── backend/
│   ├── lib/
│   │   ├── backtest/             ← src/backtest/*.py
│   │   ├── monitoring/           ← src/monitoring/{quality_assessment,performance_tracker,healthcheck,audit_logger}.py
│   │   ├── telegram_control/     ← src/control/local_command_*.py
│   │   ├── desired_state.py      ← src/control/desired_state.py
│   │   ├── selfcheck.py          ← src/settings/{validation,startup_self_check}.py
│   │   └── common/               ← (cherry-pick si server.py lo necesita)
│   └── server.py                 ← endpoints nuevos: /api/backtest/run, /api/telegram/command
├── scripts/
│   ├── run_backtest.py           ← scripts/run_backtest.py reescrito
│   ├── run_walk_forward.py       ← scripts/run_walk_forward.py reescrito
│   ├── run_quality_assessment.py ← scripts/run_quality_assessment.py reescrito
│   ├── run_self_check.py         ← scripts/run_self_check.py reescrito
│   └── seed_legacy_journal.py    ← parsea CLAUDE.md viejo y siembra MongoDB
├── config/
│   └── legacy/                   ← config/*.yaml seleccionados
├── legacy/                       ← solo lectura, no se ejecuta
│   ├── README.md                 ← explica por qué cada cosa está aquí
│   ├── mql5/                     ← Experts/ + Files/
│   ├── docs/                     ← docs viejos seleccionados
│   ├── reports/                  ← backtests + paper outputs
│   └── audit/                    ← audit_events.jsonl
└── docs/MIGRATION_FROM_LEGACY.md ← este archivo
```

---

## 3. Orden de ejecución del port

Se hace en este orden porque cada paso depende del anterior:

1. **Backup + tag git** (precondición de todo).
2. **`_shared/common/`** — utilidades base (clock, ids, jsonl, timeframes,
   enums). Sin esto no compilan los módulos portados.
3. **`analysis-mcp/lib/features/`** — features puras, sin dependencias.
4. **`analysis-mcp/lib/filters.py` + `strategies/`** — dependen de features.
5. **`analysis-mcp/lib/profiles/`** — agrega evaluación por símbolo.
6. **`analysis-mcp/lib/pretrade.py`** — gate consolidado, depende de news +
   profiles.
7. **`risk-mcp/lib/`** ports — `conviction_sizing`, `drawdown_guard`,
   `setup_memory`. El kill-switch existente del bot nuevo sigue siendo la
   fuente de verdad.
8. **`news-mcp/lib/`** ports — `event_calendar`, `relevance_ranker`,
   `sentiment_guard`, `collector`, `headline_normalizer`.
9. **`trading-mt5-mcp/lib/`** ports — `sl_tp_manager`, `trailing_stop`,
   `reconciliation`, `quality`. Se exponen como tools nuevas en `server.py`:
   `set_trailing_stop`, `update_sl_tp`, `reconcile_positions`,
   `assess_data_quality`.
10. **`backend/lib/backtest/`** — backtest engine + métricas + walk-forward.
    Endpoint `POST /api/backtest/run`.
11. **`backend/lib/telegram_control/`** — comandos bidireccionales del bot.
    Endpoint `POST /api/telegram/command` + integración con
    `telegram_notifier.py` ya existente.
12. **`backend/lib/monitoring/`** — `quality_assessment` y
    `performance_tracker` + endpoint `GET /api/quality/score`.
13. **`scripts/seed_legacy_journal.py`** — lee `xm-mt5-trading-platform/CLAUDE.md`,
    extrae la tabla de trades, y POSTea cada uno a `/api/journal` con
    `client_id = "legacy-<sha8>"`.
14. **Migración de `daily_pnl_state.json`** — copia con migración de schema a
    `risk-mcp/state.json` (bumpear `_schema_version`).
15. **Mover MQL5, docs, reports, audit a `legacy/`** — copia, no port.
16. **Apagar autostart del bot viejo** — borrar tareas programadas
    `Daurel Nightly Research`, atajos `🚀 Iniciar Bot XM.cmd`,
    `🛑 Detener Bot XM.cmd` apuntando al viejo, y reescribir versiones que
    apunten al nuevo.
17. **Borrar `xm-mt5-trading-platform/`** — solo tras (a) backup tarball
    verificado en `_archive/` y (b) tests del bot nuevo verdes.

---

## 4. Reglas de adaptación al blueprint

Cada pieza portada se reescribe respetando esto, sin excepciones:

- **Constantes hard-limit** (risk %, daily loss %, min RR, max positions,
  consecutive losses) **NUNCA** se duplican: se importan de
  `_shared/rules.py`. Si el módulo viejo tenía su propia constante
  equivalente, se elimina del módulo y se importa del shared.
- **Kill-switch**: cualquier loop que ponga órdenes o que escriba estado
  crítico chequea `from _shared.halt import is_halted` al inicio de cada
  iteración. Sin excepciones.
- **Modo `paper` por defecto**: ningún módulo portado puede enviar órdenes
  reales sin que `TRADING_MODE` esté explícitamente en `demo` o `live`.
- **Idempotencia**: cualquier endpoint o tool que escriba en `journal`,
  `deals.jsonl`, `state.json` acepta `client_id`/`client_order_id` y
  cortocircuita si ya vio ese id en los últimos 60s.
- **Tool de MCP devuelve dict**: nunca lanza excepción salvo error de
  protocolo. Errores son
  `{"ok": false, "reason": "<UPPER_SNAKE>", "detail": "<human>"}`.
- **stdout reservado para protocolo MCP**: todo log va a stderr.
- **Tests**: cada módulo portado trae sus tests. Los del bot viejo se adaptan.
  Si el módulo viejo no tenía test, se escribe uno mínimo (al menos un
  happy-path y un edge-case rechazado).
- **Type hints en todo**, Pydantic models para inputs estructurados.

Lo que **NO** se porta nunca, pase lo que pase:

- Hooks `bypass_*` (no existen en el bot viejo afortunadamente, verificar).
- Funciones que escriben a stdout en MCPs.
- Constantes risk-limits inline en strategies o decision.
- Cualquier dependencia hacia `integrations/codex_*` o `integrations/openclaw_*`
  desde un módulo de trading. Si una pieza del bot viejo lo tiene, se cortan
  esas referencias en el port.

---

## 5. Criterio de "listo para borrar el viejo"

Se cumple **toda** esta lista o no se borra:

- [ ] Tarball `_archive/xm-mt5-trading-platform-<fecha>.tar.gz` existe y `tar tzf`
      lo lista correctamente.
- [ ] Tag git `pre-legacy-migration` existe en `NEW-BOT-PRO_MAX`.
- [ ] `pytest backend/tests/` pasa.
- [ ] `pytest mcp-scaffolds/_shared/tests/` pasa.
- [ ] `pytest mcp-scaffolds/analysis-mcp/tests/` pasa con los tests portados.
- [ ] `pytest mcp-scaffolds/risk-mcp/tests/` pasa con los tests portados.
- [ ] `pytest mcp-scaffolds/news-mcp/tests/` pasa con los tests portados.
- [ ] `pytest mcp-scaffolds/trading-mt5-mcp/tests/` pasa.
- [ ] Smoke: dashboard arranca, journal muestra los trades migrados desde
      CLAUDE.md viejo.
- [ ] Smoke: `analysis-mcp.score_setup` con un OHLCV sintético devuelve un
      score con la lógica de la estrategia portada.
- [ ] Smoke: `POST /api/backtest/run` con datos sintéticos devuelve un report
      consistente con `backtest/report.py` viejo.
- [ ] No queda ninguna tarea programada de Windows que apunte a
      `xm-mt5-trading-platform`.
- [ ] No queda ningún `.cmd` en `bugbounty/` que invoque scripts del viejo.
- [ ] El usuario revisó este checklist y dio luz verde explícita.

Sólo entonces se borra `xm-mt5-trading-platform/`.

---

## 6. Lo que se va a perder (con justificación)

Honestidad: estas son las cosas del bot viejo que **no** sobreviven y por qué.

- **Toda la integración Codex/OpenClaw (`src/integrations/`, ~13k LOC).** Eran
  adapters para gestionar slots de Codex y OpenClaw del propio operador, no
  tienen relación con trading. El bot nuevo asume Claude Pro Max como
  orquestador único.
- **`analysis/agent_*` (consensus, coordinator, event_bus, launch_registry,
  state_store).** Andamiaje multi-agente para correr varios bots de análisis
  en paralelo. Innecesario en un setup donde Claude es el agente.
- **SQLite (`src/persistence/`).** Reemplazado por MongoDB + JSONL.
- **`logs/codex_enhanced_interactions.jsonl` (74 MB).** Histórico de
  interacciones con Codex; no aporta a la operación nueva.
- **Tareas programadas de Windows del viejo** (`Daurel Nightly Research 4AM`,
  autostart de demo). El nuevo bot se arranca a mano con `uvicorn` o vía
  Claude Desktop.
- **MQL5 file-bridge ejecutándose**. Los `.mq5` quedan en `legacy/` como doc
  histórica, pero el bot nuevo habla con MT5 vía paquete Python `MetaTrader5`,
  no por archivos.
- **`monitoring/dashboards.py`, `control_center_views.py`,
  `telegram_operator_output.py`.** Dashboards y vistas de operador del viejo.
  Reemplazados por la dashboard React del bot nuevo.

Si alguno de estos resulta ser crítico durante el port, **se para**, se
discute con el usuario, y se decide si se rescata. Default = se descarta.
