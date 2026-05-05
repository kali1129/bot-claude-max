"""Legal content for the SaaS — risk disclaimer, TOS and privacy policy.

These are PLAIN TEMPLATES, not legally vetted. Before going to production
with paying customers, have a lawyer review. The disclaimer is the
non-negotiable one — financial regulators (CFTC/NFA in US, FCA in UK,
ESMA in EU) require it for any service that suggests trades or runs
automated trading.

Each piece has a `version` so the frontend can detect changes and ask
existing users to re-acknowledge after material updates.
"""
from __future__ import annotations

from typing import Dict

# ─────────────────────────── RISK DISCLAIMER ───────────────────────────

RISK_DISCLAIMER_VERSION = "2026-05-05"
RISK_DISCLAIMER_MD = """\
# AVISO DE RIESGO — Trading de Forex y Derivados

**El trading de divisas (forex), CFDs y otros instrumentos apalancados
implica un alto nivel de riesgo y NO es adecuado para todos los
inversores. Existe la posibilidad de que pierdas la totalidad de tu
capital depositado, e incluso más, dependiendo del broker.**

Antes de usar este servicio leé y entendé:

1. **Pérdida potencial total.** El sistema opera con apalancamiento.
   Movimientos pequeños del precio pueden resultar en pérdidas grandes en
   relación al capital. La estrategia "no-SL" del aggregator deja correr
   las pérdidas hasta un soft-stop configurable; en escenarios extremos
   (gap de fin de semana, anuncios macro, broker caído, conexión perdida)
   ese soft-stop puede no dispararse a tiempo y la pérdida puede exceder
   el porcentaje configurado.

2. **No es asesoramiento financiero.** El servicio entrega herramientas
   y automatización; las decisiones de configurar el bot, depositar
   capital, elegir broker y aceptar trades son enteramente del usuario.
   Ningún resultado pasado garantiza resultados futuros.

3. **Backtest ≠ live.** Los resultados del backtest se calculan sobre
   datos históricos y un simulador; el live tiene slippage, spread
   variable, comisiones, latencia, requotes y períodos de baja
   liquidez que el simulador no modela perfectamente.

4. **Riesgo del broker.** Tu capital queda depositado con un broker
   externo. Si el broker quiebra, es estafa o congela retiros, este
   servicio no puede recuperarlo. Recomendamos brokers regulados
   (FCA, CySEC, ASIC) y empezar con cuenta demo.

5. **Riesgo operativo del servicio.** El servicio corre en servidores
   de terceros (Oracle Cloud, otros). Períodos de inactividad,
   actualizaciones, fallos de software o pérdida de conectividad
   pueden dejar trades sin gestión activa. Se recomienda monitorear
   las posiciones manualmente.

6. **No depositar dinero que no podés permitirte perder.**

Al usar el servicio confirmás que entendiste los riesgos y aceptás
operar bajo tu propia responsabilidad.
"""

# ─────────────────────────── TERMS OF SERVICE ───────────────────────────

TOS_VERSION = "2026-05-05"
TOS_MD = """\
# Términos de Servicio

**Última actualización:** 2026-05-05

## 1. Aceptación
Al crear una cuenta o usar el servicio aceptás estos términos. Si no
estás de acuerdo, no uses el servicio.

## 2. Descripción del servicio
Plataforma SaaS que ejecuta estrategias automatizadas de trading sobre
cuentas MetaTrader 5 conectadas por el usuario. El servicio incluye
backtest, gestión de capital, journal de operaciones y notificaciones.

## 3. Cuenta de usuario
- Sos responsable de mantener la confidencialidad de tu password.
- Una cuenta por persona. No compartir credenciales.
- Te reservamos el derecho de suspender cuentas con uso fraudulento o
  abusivo (scraping, brute-force, intentos de bypass de límites).

## 4. Sin garantías
El servicio se entrega "tal cual" (AS-IS). No garantizamos resultados,
disponibilidad continua, ni que el servicio esté libre de errores. Ver
también el [aviso de riesgo](/api/legal/risk-disclaimer).

## 5. Limitación de responsabilidad
En la máxima medida permitida por la ley, no somos responsables de
pérdidas financieras, de datos, de oportunidad o consecuenciales que
surjan del uso del servicio. La responsabilidad máxima agregada se
limita al monto que pagaste por el servicio en los 12 meses anteriores.

## 6. Propiedad intelectual
El código, diseño y contenido del servicio nos pertenecen. Tus datos
de trading siguen siendo tuyos; te otorgamos una licencia para usar
las herramientas mientras tengas cuenta activa.

## 7. Cancelación
Podés cerrar tu cuenta cuando quieras. Podemos cerrar cuentas
inactivas (sin login en 12 meses) o por violación de estos términos.

## 8. Cambios a los términos
Podemos actualizar estos términos. Cambios materiales se anuncian con
30 días de aviso por email. Al continuar usando el servicio aceptás
los nuevos términos.

## 9. Ley aplicable
Estos términos se rigen por las leyes de la jurisdicción donde opera
el operador del servicio. Disputas se resuelven en los tribunales
competentes de esa jurisdicción.

## 10. Contacto
Para reclamos, soporte o exportación de datos: el email del
administrador del servicio.
"""

# ─────────────────────────── PRIVACY POLICY ───────────────────────────

PRIVACY_VERSION = "2026-05-05"
PRIVACY_MD = """\
# Política de Privacidad

**Última actualización:** 2026-05-05

## 1. Datos que recolectamos
- **Cuenta**: email, password (hasheado con bcrypt, nunca en plano).
- **Broker**: credenciales MT5 (login, password, server) cifradas con
  AES-GCM antes de guardarse. Solo se desencriptan en memoria al
  conectar el bot.
- **Trading**: registros de cada operación (símbolo, tamaño, P&L,
  scores), configuración de estrategias, samples de equity.
- **Operacional**: IPs de login, timestamps, logs del bot. Las IPs
  se usan para rate-limiting y detección de abuso.

## 2. Para qué usamos los datos
- Operar el servicio: ejecutar trades, mostrar journal, calcular stats.
- Notificar resultados (Telegram, si lo configurás).
- Anti-fraude y rate-limiting.
- Métricas internas agregadas (sin identificar usuarios individuales).

## 3. Lo que NO hacemos
- No vendemos tus datos a terceros.
- No usamos tus trades para alimentar modelos compartidos sin tu
  permiso explícito.
- No accedemos a tu cuenta de broker para operar manualmente.

## 4. Terceros
- **MongoDB**: base de datos (alojada en el mismo VPS que el bot).
- **Telegram**: si configurás notificaciones, los mensajes se envían
  vía la Bot API de Telegram (Telegram LLC).
- **Brokers MT5**: tus credenciales se usan solo para conectar el bot
  al broker que vos elegiste.

## 5. Tus derechos
- **Acceso**: podés ver y exportar tu data (journal, settings) desde
  el dashboard.
- **Rectificación / borrado**: podés borrar tu cuenta desde Settings.
  Al borrar la cuenta, los datos se eliminan en 30 días (ventana para
  rollback de cobranzas u operación).
- **Portabilidad**: podés exportar el journal en CSV.

## 6. Seguridad
- HTTPS en todo el tráfico (Let's Encrypt).
- Passwords con bcrypt cost 12.
- Credenciales de broker cifradas en reposo.
- Backups diarios cifrados.
- Acceso al servidor por SSH con keys; sin password root.

## 7. Retención
- Cuenta activa: indefinido mientras la mantengas.
- Cuenta cerrada: 30 días, después borrado.
- Logs operacionales: 14 días con rotación automática.
- Backups: 30 días.

## 8. Contacto
Para ejercer tus derechos o reportar incidentes: el email del
administrador del servicio.
"""

# ─────────────────────────── REGISTRY ───────────────────────────

DOCUMENTS: Dict[str, Dict] = {
    "risk-disclaimer": {
        "title": "Aviso de Riesgo",
        "version": RISK_DISCLAIMER_VERSION,
        "markdown": RISK_DISCLAIMER_MD,
    },
    "tos": {
        "title": "Términos de Servicio",
        "version": TOS_VERSION,
        "markdown": TOS_MD,
    },
    "privacy": {
        "title": "Política de Privacidad",
        "version": PRIVACY_VERSION,
        "markdown": PRIVACY_MD,
    },
}


def list_documents() -> list:
    return [
        {"slug": slug, "title": d["title"], "version": d["version"]}
        for slug, d in DOCUMENTS.items()
    ]


def get_document(slug: str) -> Dict | None:
    return DOCUMENTS.get(slug)
