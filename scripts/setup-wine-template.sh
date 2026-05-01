#!/bin/bash
# setup-wine-template.sh — crea el Wine prefix template para clonar a
# usuarios nuevos.
#
# El template lleva: Python 3.11 + dependencias del bot + MT5 terminal.
# Cuando un usuario pide /bot/start por primera vez, se hace
#   cp -r /opt/trading-bot/wine_template /opt/trading-bot/users/{id}/wine
# y arranca su auto_trader.py contra ese prefix.
#
# Este script tiene 3 modos:
#   --clone-from-admin  : copia el prefix actual del admin (recomendado).
#   --check             : verifica si el template existe y es funcional.
#   --refresh           : borra el template viejo y recrea desde admin.
#
# Uso típico (idempotente): bash setup-wine-template.sh --clone-from-admin

set -euo pipefail

ADMIN_PREFIX="/opt/trading-bot/wine"
TEMPLATE_PREFIX="/opt/trading-bot/wine_template"
USERS_BASE="/opt/trading-bot/users"

MODE="${1:-}"
if [ -z "$MODE" ]; then
    cat <<EOF
setup-wine-template.sh — gestión del Wine prefix template

Uso:
  $0 --clone-from-admin     Crea el template copiando el prefix del admin.
  $0 --check                Verifica que el template existe y tiene MT5.
  $0 --refresh              Borra el template y lo recrea (usar tras
                            reinstalar MT5 en el admin).

Setup recomendado para FASE 3:
  1. Asegurate que el admin (cuenta XM 309780622) está conectada y
     opera bien desde /opt/trading-bot/wine.
  2. Corré: bash $0 --clone-from-admin
  3. Verificá: bash $0 --check
  4. Reiniciá el backend: sudo systemctl restart trading-backend
  5. Cualquier usuario que llame /bot/start ahora va a tener su prefix
     dedicado clonado del template.
EOF
    exit 0
fi

case "$MODE" in
  --check)
    echo "==> Verificando template en $TEMPLATE_PREFIX"
    if [ ! -d "$TEMPLATE_PREFIX" ]; then
      echo "❌ Template NO existe. Correr: $0 --clone-from-admin"
      exit 1
    fi
    if [ ! -d "$TEMPLATE_PREFIX/drive_c/Program Files/Python311" ]; then
      echo "❌ Python311 NO encontrado en template"
      exit 1
    fi
    if ! ls "$TEMPLATE_PREFIX/drive_c/Program Files/" | grep -qi "MT5\|MetaTrader"; then
      echo "❌ MT5 terminal NO encontrado en template"
      exit 1
    fi
    SIZE=$(du -sh "$TEMPLATE_PREFIX" | awk '{print $1}')
    echo "✓ Template OK — tamaño: $SIZE"
    USERS_COUNT=$(ls "$USERS_BASE" 2>/dev/null | wc -l)
    echo "✓ Usuarios con prefix activo: $USERS_COUNT"
    df -h "$USERS_BASE" 2>/dev/null | tail -1
    ;;

  --clone-from-admin)
    if [ ! -d "$ADMIN_PREFIX" ]; then
      echo "❌ El prefix admin NO existe en $ADMIN_PREFIX"
      echo "   Configurá primero el bot del admin antes de crear el template."
      exit 1
    fi
    if [ -d "$TEMPLATE_PREFIX" ]; then
      echo "⚠ Template ya existe. Usá --refresh si querés recrearlo."
      exit 1
    fi
    echo "==> Clonando admin prefix → template..."
    echo "    src: $ADMIN_PREFIX"
    echo "    dst: $TEMPLATE_PREFIX"
    SIZE=$(du -sh "$ADMIN_PREFIX" | awk '{print $1}')
    echo "    tamaño: $SIZE"
    echo "    esto puede tardar 1-3 minutos..."
    sudo cp -r "$ADMIN_PREFIX" "$TEMPLATE_PREFIX"
    sudo chown -R deploy:deploy "$TEMPLATE_PREFIX"
    # Limpiar credenciales del admin del registry del template
    # (cada usuario hará login fresh con sus creds)
    USER_REG="$TEMPLATE_PREFIX/user.reg"
    if [ -f "$USER_REG" ]; then
      # XM Global guarda el último login en un campo del .ini de la cuenta.
      # Borramos los archivos de cuentas del MT5 para que cada user empiece
      # limpio.
      sudo rm -f "$TEMPLATE_PREFIX/drive_c/Program Files/XM Global MT5/Config/accounts.dat" 2>/dev/null || true
      sudo rm -rf "$TEMPLATE_PREFIX/drive_c/users/deploy/AppData/Roaming/MetaQuotes/Terminal/"*/config/accounts.ini 2>/dev/null || true
    fi
    sudo mkdir -p "$USERS_BASE"
    sudo chown -R deploy:deploy "$USERS_BASE"
    echo "✓ Template creado"
    bash "$0" --check
    ;;

  --refresh)
    if [ ! -d "$TEMPLATE_PREFIX" ]; then
      echo "Template no existe — creando desde cero..."
      bash "$0" --clone-from-admin
      exit $?
    fi
    echo "==> Borrando template viejo..."
    sudo rm -rf "$TEMPLATE_PREFIX"
    echo "==> Re-clonando desde admin..."
    bash "$0" --clone-from-admin
    ;;

  *)
    echo "Uso inválido: $MODE"
    echo "Probá: $0 (sin args para help)"
    exit 1
    ;;
esac
