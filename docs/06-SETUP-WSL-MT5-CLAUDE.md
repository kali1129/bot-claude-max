# 06 — Setup Completo: WSL + MT5 + Claude Desktop + 4 MCPs

> Guía completa, paso a paso, desde laptop limpia hasta primera operación asistida en demo. Tiempo estimado: **3-4 horas** distribuidas en 1-2 sesiones. Nivel: intermedio (manejas terminal, Python básico, instalas software).

## Pre-requisitos

| Item | Mínimo | Recomendado |
|---|---|---|
| OS | Windows 10 64-bit | Windows 11 |
| RAM | 8 GB | 16 GB |
| Disco libre | 20 GB | 50 GB SSD |
| Conexión | 10 Mbps | 50 Mbps con cable |
| Cuenta MT5 demo | sí (broker que prefieras) | Pepperstone, IC Markets, Exness |
| Suscripción Claude | Pro Max ($200/mo) | (necesario para MCPs) |
| Editor | VSCode | VSCode + WSL extension |

---

## Paso 1 — Habilitar WSL2 + Ubuntu 22.04

### En PowerShell **como administrador**:

```powershell
wsl --install -d Ubuntu-22.04
```

**Reinicia Windows**. Cuando vuelva, Ubuntu se inicia automáticamente y pide usuario/password (anótalos).

### Verifica:
```powershell
wsl --status
# Default Distribution: Ubuntu-22.04
# Default Version: 2
```

### Dentro de Ubuntu (WSL):
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git curl build-essential

# Verifica
python3.11 --version  # 3.11.x
pip3 --version
```

---

## Paso 2 — Instalar Python en Windows nativo (REQUERIDO para MT5 MCP)

La librería `MetaTrader5` solo funciona con Python de Windows nativo, no con el de WSL.

### 2.1 Descargar instalador
Ve a https://www.python.org/downloads/windows/ → Python 3.11.x (64-bit installer).

### 2.2 Instalar
**IMPORTANTE**: Marca ✅ **"Add python.exe to PATH"** en la primera pantalla.
**IMPORTANTE**: Selecciona "Install Now" (admin install opcional).

### 2.3 Verifica en PowerShell normal (no admin):
```powershell
python --version       # 3.11.x
pip --version
where.exe python       # C:\Users\<tu>\AppData\Local\Programs\Python\Python311\python.exe
```

### 2.4 Pre-instala dependencias core
```powershell
pip install --upgrade pip
pip install MetaTrader5 mcp httpx pandas python-dotenv beautifulsoup4 pydantic pandas-ta
```

---

## Paso 3 — Instalar y configurar MetaTrader 5

### 3.1 Elegir broker (recomendaciones para $800)

| Broker | Pros | Contras | Cuenta mínima |
|---|---|---|---|
| **Pepperstone** | Spreads muy bajos, ECN | Regulación AU/UK | $200 |
| **IC Markets** | Spreads ECN, bajo slippage | Sin regulación EU | $200 |
| **Exness** | Sin mínimo, micro-lotes | Spreads variables | $0 |
| **OANDA** | US-friendly, regulado | Spreads más altos | $0 |

Para empezar, **abre cuenta DEMO con cualquiera de ellos**, no real todavía.

### 3.2 Descargar MT5
Cada broker tiene su build branded de MT5. Usa el del broker, no el genérico de MetaQuotes (mejor compatibilidad).

### 3.3 Instalar y loguear DEMO
- Abre MT5 → File → Open an Account → Demo
- Anota: **Login** (numérico), **Password Investor** (read-only) y **Password Master** (trading), **Server** (e.g. `Pepperstone-Demo`).

### 3.4 Habilitar trading algorítmico
MT5 → Tools → Options → Expert Advisors:
- ✅ Allow algorithmic trading
- ✅ Allow DLL imports
- ✅ Allow WebRequest for listed URL (déjalo vacío)

### 3.5 Test rápido de conexión Python
En PowerShell:
```powershell
python -c "import MetaTrader5 as mt5; print(mt5.initialize()); print(mt5.account_info()); mt5.shutdown()"
```
Debería imprimir `True` y los datos de tu cuenta demo.

⚠️ Si imprime `False`: el terminal MT5 debe estar **abierto** durante la inicialización.

---

## Paso 4 — Instalar Claude Desktop

### 4.1 Descargar
https://claude.ai/download → Windows version → instalar.

### 4.2 Login
Login con tu cuenta **Pro Max** ($200/mes).

### 4.3 Verificar soporte MCP
Settings → Developer → debe verse "MCP Servers" sección.

Si no aparece: actualiza Claude Desktop a la última versión.

---

## Paso 5 — Crear estructura de carpetas para MCPs

### En PowerShell:
```powershell
$base = "$env:USERPROFILE\mcp"
mkdir $base
cd $base
mkdir news-mcp, trading-mt5-mcp, analysis-mcp, risk-mcp, logs

# Verifica
ls
# news-mcp  trading-mt5-mcp  analysis-mcp  risk-mcp  logs
```

---

## Paso 6 — Construir cada MCP con Claude Code

### 6.1 Abre Claude Desktop
Inicia una conversación nueva.

### 6.2 Para cada MCP (4 en total):

1. Abre el dashboard web → sección **MCP Stack**.
2. Click en **"Copy Prompt"** del MCP_01 (News).
3. En Claude Desktop pega:
   ```
   Vas a crear un MCP server. Crea estos archivos en mi máquina,
   yo los voy a copiar a C:\Users\<usuario>\mcp\news-mcp\:

   [PEGA EL PROMPT COMPLETO AQUÍ]
   ```
4. Claude generará:
   - `server.py`
   - `requirements.txt`
   - `.env.example`
   - posiblemente librerías auxiliares en `lib/`

5. Copia los archivos a `C:\Users\<usuario>\mcp\news-mcp\`.
6. Crea `.env` (a partir de `.env.example`) con tus keys reales.

### 6.3 Repite para los otros 3:
- MCP_02 (Trading-MT5) → `trading-mt5-mcp/`
- MCP_03 (Analysis) → `analysis-mcp/`
- MCP_04 (Risk) → `risk-mcp/`

### 6.4 Instala dependencias por cada MCP

```powershell
cd C:\Users\$env:USERNAME\mcp\news-mcp
pip install -r requirements.txt

cd ..\trading-mt5-mcp
pip install -r requirements.txt

cd ..\analysis-mcp
pip install -r requirements.txt

cd ..\risk-mcp
pip install -r requirements.txt
```

### 6.5 Test individual de cada server (smoke)

Cada server.py debe poder ejecutarse standalone:
```powershell
cd C:\Users\$env:USERNAME\mcp\news-mcp
python server.py
# Si no hay error, Ctrl+C y listo
```

Si revienta, lee el error y arregla antes de configurar Claude.

---

## Paso 7 — Configurar `claude_desktop_config.json`

### 7.1 Ubicación del archivo
```
%APPDATA%\Claude\claude_desktop_config.json
```

En PowerShell:
```powershell
notepad $env:APPDATA\Claude\claude_desktop_config.json
```

### 7.2 Contenido
Reemplaza `<USUARIO>` por tu nombre real y rellena las API keys:

```json
{
  "mcpServers": {
    "news": {
      "command": "python",
      "args": ["C:\\Users\\<USUARIO>\\mcp\\news-mcp\\server.py"],
      "env": {
        "FINNHUB_API_KEY": "ckxxxxxxxxxxxxxx",
        "NEWSAPI_KEY": "xxxxxxxxxxxxxxxxxxxx"
      }
    },
    "trading": {
      "command": "C:\\Users\\<USUARIO>\\AppData\\Local\\Programs\\Python\\Python311\\python.exe",
      "args": ["C:\\Users\\<USUARIO>\\mcp\\trading-mt5-mcp\\server.py"],
      "env": {
        "MT5_LOGIN": "12345678",
        "MT5_PASSWORD": "tu_password_demo",
        "MT5_SERVER": "Pepperstone-Demo"
      }
    },
    "analysis": {
      "command": "python",
      "args": ["C:\\Users\\<USUARIO>\\mcp\\analysis-mcp\\server.py"]
    },
    "risk": {
      "command": "python",
      "args": ["C:\\Users\\<USUARIO>\\mcp\\risk-mcp\\server.py"],
      "env": {
        "STARTING_BALANCE": "800",
        "MAX_RISK_PER_TRADE_PCT": "1.0",
        "MAX_DAILY_LOSS_PCT": "3.0",
        "STATE_FILE": "C:\\Users\\<USUARIO>\\mcp\\risk-mcp\\state.json"
      }
    }
  }
}
```

⚠️ **Path al python.exe del trading-mcp**: si lo apuntas al de WSL, fallará. Apunta al de Windows nativo (`C:\Users\<usuario>\AppData\Local\Programs\Python\Python311\python.exe`).

### 7.3 Reiniciar Claude Desktop completamente
Cierra desde icono en system tray → reabre.

### 7.4 Verifica que los 4 MCPs cargaron
En Claude Desktop, abre cualquier conversación y mira el icono de MCP (esquina inferior derecha del input). Debe listar 4 servers conectados.

---

## Paso 8 — Validación end-to-end (DEMO, primer día)

### Test 1: Read-only en cada MCP

```
Tú: "Trae el calendario económico HIGH-impact de hoy"
Claude: news.get_economic_calendar(...) → [...]
```

```
Tú: "¿Estado de cuenta?"
Claude: trading.get_account_info() → balance demo
```

```
Tú: "Analiza EURUSD M15 últimas 200 velas"
Claude: trading.get_rates(...)
        analysis.indicators(...)
        analysis.market_structure(...)
        → Reporta trend, RSI, S/R
```

```
Tú: "¿Cuál es mi estado de risk hoy?"
Claude: risk.daily_status() → "Día limpio, 0 trades, can_trade=true"
```

### Test 2: Score de un setup
```
Tú: "Si quiero entrar long EURUSD a 1.0850 con SL 1.0830 y TP 1.0890,
     ¿cómo califica el setup?"
Claude: analysis.score_setup(...) → score 78, TAKE
```

### Test 3: Cálculo de lotaje
```
Tú: "Calcula lotaje para ese trade"
Claude: trading.get_account_info() → balance
        trading.symbol_info("EURUSD") → tick info
        risk.calc_position_size(...) → 0.03 lots
```

### Test 4: Guardas activan
```
Tú: "Envía la orden con SL 1.0830 y TP 1.0860 (R:R 0.5)"
Claude: trading.place_order(...) → REJECTED (R:R < 2.0) ✅
```

### Test 5: Trade real demo (final)
```
Tú: "Setup A+ confirmado. Envía la orden con SL 1.0830 y TP 1.0890"
Claude: trading.place_order(...) → ticket 123...
        Después de cerrar:
        Claude: trading.close_position(...) → +$15
                risk.register_trade(profit=15, r_multiple=2.0, ...) → registrado
```

✅ Si los 5 tests pasan: tu sistema está funcional.

---

## Paso 9 — Periodo demo (2 semanas mínimo)

### Reglas de oro durante demo:
1. **Mismo capital ficticio que el real**: configura tu demo con $800 (o lo más cercano que permita el broker).
2. **Mismo riesgo**: 1% = $8.
3. **Documenta TODOS los trades** en el dashboard `/journal`.
4. **No saltes reglas porque es demo**: el músculo de la disciplina solo se entrena bajo presión real-percibida.

### Métricas para "graduarte" a real:
- ≥ **40 trades** documentados
- **expectancy ≥ +0.30R** sobre últimos 30 trades
- **0 violaciones** de regla en 2 semanas seguidas
- Te sientes **aburrido** ejecutando (señal de internalización)

### Si fracasas en demo:
- ❌ <30 trades en 2 semanas → trades muy poco frecuentes, revisa setups que aceptas
- ❌ Expectancy negativa → tu rúbrica de score_setup necesita tuning, o tu disciplina al cerrar ganadores/perdedores está rota
- ❌ Violaste regla X veces → no estás listo para real. Rehaz 2 semanas más.

---

## Paso 10 — Migración a cuenta REAL ($800)

Solo después de pasar Paso 9. Acciones:

### 10.1 Abre cuenta real con el mismo broker
Deposita $800.

### 10.2 Cambia credenciales en `claude_desktop_config.json`
```json
"trading": {
  "env": {
    "MT5_LOGIN": "tu_cuenta_REAL",
    "MT5_PASSWORD": "tu_password_real",
    "MT5_SERVER": "Pepperstone-Live01"  // server REAL, no Demo
  }
}
```

### 10.3 Reduce riesgo TEMPORALMENTE a 0.5%
Edita `trading-mt5-mcp/server.py`:
```python
MAX_RISK_PER_TRADE_PCT = 0.5  # primera semana real
```
Y `risk-mcp` env:
```
MAX_RISK_PER_TRADE_PCT=0.5
```

### 10.4 Reinicia Claude Desktop.

### 10.5 Resetea `state.json` del risk-mcp:
```powershell
del C:\Users\$env:USERNAME\mcp\risk-mcp\state.json
# se recreará al primer call con balance=800 (real)
```

### 10.6 Primera semana real:
- 1 trade/día máximo
- Riesgo 0.5%
- Documentación obsesiva

### 10.7 Si todo bien tras 7 días → sube a 1% riesgo (vuelve a editar `MAX_RISK_PER_TRADE_PCT = 1.0` y reinicia).

---

## Mantenimiento y operación diaria

### Rutina de mañana (antes de operar)
1. Abre dashboard web
2. Sección **Daily Checklist** → completa pre-mercado (7 items)
3. Abre Claude Desktop
4. Pídele: *"Estado del día y top 3 oportunidades en NAS100, EURUSD, XAUUSD"*

### Rutina de noche (post-cierre)
1. Cierra posiciones intradía si aplica
2. Dashboard → **Trade Journal** → registra trades del día con notas y screenshot link
3. Dashboard → **Daily Checklist** → completa post-mercado (5 items)
4. Cierra Claude. No revises cuenta hasta mañana.

### Rutina semanal (domingo)
1. Dashboard → revisa equity curve
2. Pide a Claude: *"Calcula mi expectancy de últimos 30 trades y dime qué estrategia funcionó mejor"*
3. Anota 1 mejora a probar la próxima semana

---

## Troubleshooting general

| Síntoma | Causa probable | Fix |
|---|---|---|
| Claude no ve los MCPs | config JSON malformado | `python -m json.tool $env:APPDATA\Claude\claude_desktop_config.json` |
| MCP "trading" falla en init | terminal MT5 cerrado | Abre MT5 antes de iniciar Claude |
| WSL python: `MetaTrader5` no instala | Es esperado | El trading-mcp DEBE correr con python Windows |
| Risk-mcp `state.json` corrompido | crash mid-write | Borra y se recrea |
| News-mcp 429 ForexFactory | UA bloqueado | Cambia FF_USER_AGENT, baja frecuencia |
| Place_order siempre falla | R:R real < 2 | Ajusta TP o no operes |

---

## Backup recomendado

Cada domingo:
```powershell
$timestamp = Get-Date -Format "yyyy-MM-dd"
Copy-Item -Recurse C:\Users\$env:USERNAME\mcp C:\Users\$env:USERNAME\backups\mcp-$timestamp
```

Esto preserva `state.json`, `deals.jsonl`, y configs.

---

## Costos mensuales estimados

| Item | USD/mes |
|---|---|
| Claude Pro Max | $200 |
| Finnhub free tier | $0 |
| NewsAPI free tier | $0 |
| Broker MT5 (sin comisión, spread incluido) | $0 |
| Internet (asumido) | — |
| **Total marginal** | **$200** |

Para que el sistema sea **rentable**, debes generar > $200/mes con $800. Eso es 25% mensual sobre $800. Si tu expectancy es +0.4R y arriesgas 1% por trade, necesitas ~62 trades positivos al mes (~3 al día). **Es ambicioso pero alcanzable** si el sistema funciona.

Si en el primer mes real haces < $200, el sistema te está costando dinero neto. Considera:
- Aumentar tamaño de cuenta a $2000 (cambia el ratio)
- Reducir frecuencia y aumentar R:R objetivo
- Pausar y revisar expectancy

---

## Recursos adicionales

- [MCP docs](https://modelcontextprotocol.io)
- [MetaTrader5 Python API](https://www.mql5.com/en/docs/integration/python_metatrader5)
- [Finnhub API](https://finnhub.io/docs/api)
- [pandas-ta docs](https://github.com/twopirllc/pandas-ta)
- [ForexFactory calendar](https://www.forexfactory.com/calendar)

---

## Checklist final de setup

- [ ] WSL2 + Ubuntu 22.04 instalado
- [ ] Python 3.11 en Windows nativo + dependencias preinstaladas
- [ ] MT5 instalado, demo logueada, "Allow algo trading" ✅
- [ ] Test `mt5.initialize()` retorna `True`
- [ ] Claude Desktop instalado con cuenta Pro Max
- [ ] 4 carpetas creadas en `~/mcp/`
- [ ] 4 MCPs construidos con Claude Code y testeados standalone
- [ ] `claude_desktop_config.json` con 4 mcpServers
- [ ] Claude Desktop ve los 4 MCPs (icono inferior)
- [ ] 5 tests del Paso 8 pasan
- [ ] API keys de Finnhub y NewsAPI obtenidas
- [ ] Periodo demo iniciado, primer trade documentado en dashboard
- [ ] Backup semanal programado

Listo. Bienvenido a la operación asistida. **Que la disciplina te acompañe.**
