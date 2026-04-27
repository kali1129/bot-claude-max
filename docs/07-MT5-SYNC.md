# 07 — MT5 → Journal Sync

> El usuario nunca registra trades a mano. Cada deal cerrado en MT5 fluye
> automáticamente al journal del dashboard, con idempotency key, en menos de
> 60 segundos. Si esta capa falla, la dashboard miente sobre tu equity y las
> guardas que dependen del journal toman decisiones con datos viejos.

## Problema que resuelve

Sin sync, el sistema tiene **dos fuentes de verdad** que divergen el primer
día:

- MT5 sabe el equity real (commissions, swap, slippage).
- Dashboard muestra el equity calculado a partir de trades que el usuario
  recordó registrar manualmente.

La discrepancia crece silenciosamente, y la regla "si daily_pl_pct ≤ -3% halt"
del backend opera sobre datos falsos.

## Solución (en 1 frase)

`trading-mt5-mcp` corre un **poller en background** que cada 30 s pide a MT5
los deals desde el último timestamp visto, y los empuja al backend con un
`client_id = "mt5-deal-{ticket}"`. El backend ya es idempotente sobre ese
campo (ver `backend/server.py:create_trade`).

## Arquitectura

```
┌──────────────────────────────────────────┐
│ trading-mt5-mcp (Windows native python)  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ Sync Poller (asyncio task)         │  │
│  │   - run every 30s                  │  │
│  │   - mt5.history_deals_get(...)     │  │
│  │   - filter ticket > last_seen      │  │
│  │   - POST each to dashboard         │  │
│  │   - persist last_seen on success   │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ State                              │  │
│  │   ~/mcp/trading-mt5-mcp/sync.json  │  │
│  │   {"last_seen_ticket": 123456789}  │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
                 │
                 │ HTTP POST + Bearer
                 ▼
        ┌────────────────────┐
        │  Backend dashboard │
        │  /api/journal      │
        │  client_id check   │
        │  → upsert          │
        └────────────────────┘
                 │
                 ▼
        ┌────────────────────┐
        │  MongoDB           │
        │  trades collection │
        └────────────────────┘
```

## State (`sync.json`)

```json
{
  "_schema_version": 1,
  "last_seen_ticket": 123456789,
  "last_run_utc": "2026-04-27T14:32:11Z",
  "errors_last_run": 0
}
```

Persistencia atómica (mismo patrón que risk-mcp's state.json).

## Ciclo del poller

```python
async def sync_loop():
    while True:
        try:
            await sync_once()
        except Exception as e:
            log.exception("sync_once failed: %s", e)
        await asyncio.sleep(30)


async def sync_once() -> dict:
    state = load_state()
    last = state["last_seen_ticket"]

    # Pull last 24h of deals (cheap, MT5 caches in memory).
    since = datetime.now(timezone.utc) - timedelta(days=1)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    new_deals = [d for d in deals if d.ticket > last]
    new_deals.sort(key=lambda d: d.ticket)

    pushed, failed = 0, 0
    max_seen = last
    for d in new_deals:
        payload = deal_to_journal_payload(d)
        ok = await push_to_dashboard(payload)
        if ok:
            pushed += 1
            max_seen = max(max_seen, d.ticket)
        else:
            failed += 1
            break  # stop on first failure to preserve ordering

    state["last_seen_ticket"] = max_seen
    state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    state["errors_last_run"] = failed
    save_state(state)
    return {"pushed": pushed, "failed": failed, "last": max_seen}
```

## Mapeo `MT5 deal → journal entry`

```python
def deal_to_journal_payload(d) -> dict:
    side = "buy" if d.type == mt5.DEAL_TYPE_BUY else "sell"
    return {
        "client_id":  f"mt5-deal-{d.ticket}",
        "source":     "mt5-sync",
        "date":       datetime.fromtimestamp(d.time, timezone.utc).date().isoformat(),
        "symbol":     d.symbol,
        "side":       side,
        "strategy":   parse_comment_for_strategy(d.comment) or "unknown",
        "entry":      d.price,
        "exit":       d.price,           # for closing deals; see below
        "sl":         lookup_position_sl(d.position_id) or d.price,
        "tp":         lookup_position_tp(d.position_id) or None,
        "lots":       d.volume,
        "pnl_usd":    d.profit + d.commission + d.swap,
        "r_multiple": compute_r(d),
        "status":     "closed-win" if d.profit > 0 else "closed-loss" if d.profit < 0 else "closed-be",
        "notes":      f"sync {d.comment}",
    }
```

**Notas de implementación**:

- Un trade en MT5 tiene `deal_open` y `deal_close`. Sólo emitimos el `client_id`
  con el `ticket` del **deal de cierre** — eso garantiza una sola fila por
  trade.
- `parse_comment_for_strategy` busca prefijos como `MTF+OB`, `ORB`, `EMA-PB`
  que el `place_order` haya escrito en el comment del request.
- `compute_r(d)` necesita el SL y entry originales: leer del cache de
  `place_order` (un dict en memoria keyed por `position_id`), o de
  `orders.jsonl` si el cache se perdió tras un restart.

## `push_to_dashboard`

```python
async def push_to_dashboard(payload: dict) -> bool:
    url = f"{DASHBOARD_URL.rstrip('/')}/api/journal"
    headers = {"Content-Type": "application/json"}
    if DASHBOARD_TOKEN:
        headers["Authorization"] = f"Bearer {DASHBOARD_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as h:
            r = await h.post(url, json=payload, headers=headers)
        if r.status_code == 200:
            return True
        log.warning("push failed %s %s: %s", r.status_code, payload["client_id"], r.text[:200])
        return False
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        log.warning("push exception for %s: %s", payload["client_id"], e)
        return False
```

## Idempotency garantizada por el backend

Backend (ya implementado, ver `backend/server.py:create_trade`):

```python
if payload.client_id:
    existing = await db.trades.find_one({"client_id": payload.client_id})
    if existing:
        return existing  # 200, mismo objeto, no duplica
```

Combined with `db.trades.create_index("client_id", unique=True, sparse=True)`,
incluso un race condition entre dos sincronizaciones simultáneas (por bug de
restart) no crea duplicados.

## Tests obligatorios

```python
@pytest.mark.asyncio
async def test_sync_pushes_new_deals_only(monkeypatch, tmp_path):
    monkeypatch.setattr("sync.STATE_FILE", str(tmp_path / "sync.json"))
    fake_deals = [_deal(ticket=100), _deal(ticket=101), _deal(ticket=102)]
    monkeypatch.setattr("sync.mt5.history_deals_get", lambda *a: fake_deals)
    pushed = []
    monkeypatch.setattr("sync.push_to_dashboard", lambda p: pushed.append(p) or True)

    res = await sync_once()
    assert res["pushed"] == 3

    # Second run: nothing new
    pushed.clear()
    res = await sync_once()
    assert res["pushed"] == 0


@pytest.mark.asyncio
async def test_sync_stops_on_first_failure(monkeypatch, tmp_path):
    """Order matters; if push fails on ticket 101, ticket 102 must wait next cycle."""
    fake_deals = [_deal(ticket=100), _deal(ticket=101), _deal(ticket=102)]
    monkeypatch.setattr("sync.mt5.history_deals_get", lambda *a: fake_deals)
    counter = {"n": 0}
    def push(p):
        counter["n"] += 1
        return counter["n"] != 2  # fail on 2nd
    monkeypatch.setattr("sync.push_to_dashboard", push)

    res = await sync_once()
    assert res["pushed"] == 1
    assert res["failed"] == 1

    state = load_state()
    assert state["last_seen_ticket"] == 100  # never advanced past failure
```

## Configuración

En `mcp-scaffolds/trading-mt5-mcp/.env.example`:

```
DASHBOARD_URL=http://localhost:8000
DASHBOARD_TOKEN=<paste backend DASHBOARD_TOKEN here>
SYNC_INTERVAL_SECONDS=30
```

## Edge cases tratados explícitamente

| Caso | Manejo |
|---|---|
| MT5 reinicia → ticket counter intacto | sigue funcionando, `last_seen` es por broker. |
| Dashboard apagado | poller falla con timeout, no avanza `last_seen`, próximo ciclo reintenta. |
| Cambio de broker (`MT5_LOGIN` distinto) | `last_seen_ticket` ya no aplica; el usuario debe `rm sync.json` para empezar. Documentar esto. |
| Trade abierto pre-MCP | aparece en history como deal con `entry == price` y `position_id` desconocido. Marcar como `status: closed-*` y `strategy: pre-sync`. |
| Volumen parcial (close 0.01 de 0.03 lotes) | MT5 lo trata como un deal. Cada cierre parcial → su propia fila. R-multiple por fila. |
| Reloj WSL ≠ Windows reloj | usar `datetime.fromtimestamp(d.time, timezone.utc)` siempre. Nunca `time.time()` para fechas de MT5. |

## Por qué el backend no hace pull (en lugar de push)

El backend vive en WSL. MT5 vive en Windows nativo. WSL puede llamar a
`localhost:Windows`, pero el inverso es frágil. Además, el `trading-mt5-mcp`
ya está en el camino crítico — meter ahí el poller no añade superficie de
fallo, mientras que un backend que lee MT5 introduce un nuevo camino de
acoplamiento.
