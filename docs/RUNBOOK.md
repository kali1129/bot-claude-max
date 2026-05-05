# Runbook — operaciones del trading-bot SaaS

VPS: `trading-bot` (alias SSH) — Oracle Cloud E5 4 vCPU / 8 GB.
Public: https://botnuevo.duckdns.org → nginx → uvicorn :8000.

## Servicios systemd

```bash
trading-backend.service        # FastAPI (uvicorn 2 workers)
trading-mt5-mcp.service        # MCP MT5 (Wine Python)
trading-auto-trader.service    # Estrategia activa (Wine Python)
trading-sync-loop.service      # Polling MT5 → MongoDB
trading-analysis-mcp.service   # MCP analysis (SSE)
trading-risk-mcp.service       # MCP risk (SSE)
trading-news-mcp.service       # MCP news (SSE)
trading-telegram.service       # Notificaciones
mongod (docker)                # DB
xvfb.service                   # Virtual display para Wine
```

```bash
sudo systemctl status trading-auto-trader
sudo systemctl restart trading-backend
journalctl -u trading-auto-trader -n 50 -f
```

## Estado del aggregator

```bash
cat /opt/trading-bot/state/aggregator_positions.json     # posiciones tracked
cat /opt/trading-bot/state/strategy_config.json          # config activa
cat /opt/trading-bot/state/strategy_config.json.pre-aggregator   # backup pre-aggregator
```

Rollback aggregator → estrategia anterior:
```bash
sudo cp /opt/trading-bot/state/strategy_config.json.pre-aggregator \
        /opt/trading-bot/state/strategy_config.json
sudo systemctl restart trading-auto-trader
```

## Backups MongoDB

Cron diario 03:00 UTC, retención 30 días. Script: `/usr/local/bin/mongo-backup.sh`. Output: `/opt/trading-bot/backups/mongo/YYYY-MM-DD_HH-MM.archive.gz`.

Backup manual:
```bash
sudo /usr/local/bin/mongo-backup.sh
ls -la /opt/trading-bot/backups/mongo/
```

Restore:
```bash
gunzip < /opt/trading-bot/backups/mongo/YYYY-MM-DD_HH-MM.archive.gz | \
    docker exec -i mongodb mongorestore --archive --drop
```

> **TODO**: enviar backups a S3 (off-site). Hoy quedan en el mismo VPS — si muere el disco, se pierden.

## Logs y rotación

- systemd journal: `journalctl -u <service>` (no rotación manual; gestiona systemd con SystemMaxUse).
- `/opt/trading-bot/logs/*.jsonl`: rotación diaria, 14 días, comprimido (`/etc/logrotate.d/trading-bot`).
- `/var/log/mongo-backup.log`: rotación semanal, 8 semanas.

## Healthchecks rápidos

```bash
curl -s https://botnuevo.duckdns.org/api/health
# {"ok":true,"db":true,"auth":true}

curl -s https://botnuevo.duckdns.org/api/legal | jq .

# Swagger: https://botnuevo.duckdns.org/api/swagger
```

## Rate-limits activos

- `POST /api/auth/login` → 10 / minuto / IP
- `POST /api/auth/register` → 5 / hora / IP

Identificación de cliente: usa header `X-Forwarded-For` (nginx ya inyecta), fallback a `remote_addr`.

> **Nota**: el limiter es in-memory por worker. Con 2 workers uvicorn el cap efectivo es ~2× el configurado. Para multi-host, mover a Redis (limits storage backend).

## Disaster recovery

**Si el VPS muere:**
1. Provisionar VPS nuevo (OCI E5 4vCPU/8GB mínimo).
2. Restaurar `/opt/trading-bot/` desde último backup off-site (TODO).
3. Restaurar Mongo desde último archive.
4. Re-configurar broker creds (cifradas, requieren JWT_SECRET y crypto_box.master_key originales — guardalos también off-site).
5. Reiniciar servicios systemd.

**Si Mongo se corrompe:**
1. Stop containers: `docker stop mongodb`.
2. Backup volume actual: `docker run --rm -v mongodb_data:/d -v $PWD:/b alpine tar czf /b/mongo-corrupt.tgz /d`.
3. Restore último archive (ver arriba).

## CI/CD

GitHub Actions corre en cada PR (`.github/workflows/ci.yml`):
- ruff lint
- pytest (backend)
- AST parse (mt5-mcp)

Local: `pre-commit install` después de `pip install pre-commit`. Hooks corren en cada commit.

## Comandos peligrosos (NO correr a la ligera)

```bash
# RESET aggregator state (pierde tracking de posiciones abiertas)
echo '{}' > /opt/trading-bot/state/aggregator_positions.json

# DROP DB (pierde TODO)
docker exec mongodb mongosh --eval 'db.getSiblingDB("trading_dashboard").dropDatabase()'

# Force-stop bot inmediato
sudo systemctl stop trading-auto-trader

# Halt total (kill switch global, leído por place_order)
touch ~/mcp/.HALT
```
