#!/usr/bin/env bash
# Аварийное восстановление: выключить защищённый канал Noise и вернуть
# вход по токену WS_SECRET (docs/security/KEYS.md, «Восстановление»).
#
#   sudo scripts/secure_recovery.sh          # SECURE_CHANNEL=off, рестарт
#   sudo scripts/secure_recovery.sh --undo   # убрать переопределение, рестарт
#
# Не трогает .env, ключи и реестр (memory/secure/): переопределение — через
# drop-in systemd (переменная окружения процесса главнее значения из .env:
# config.py загружает .env без override). Ключи остаются — после --undo
# устройства подключаются снова без нового спаривания.
set -euo pipefail

UNIT="${SAKURA_UNIT:-sakura}"
DROPIN_DIR="/etc/systemd/system/${UNIT}.service.d"
DROPIN="${DROPIN_DIR}/secure-recovery.conf"

if [[ "${1:-}" == "--undo" ]]; then
    if [[ -f "$DROPIN" ]]; then
        rm -f "$DROPIN"
        echo "Переопределение снято: $DROPIN"
    else
        echo "Переопределения не было ($DROPIN)"
    fi
else
    mkdir -p "$DROPIN_DIR"
    cat > "$DROPIN" <<'CONF'
# scripts/secure_recovery.sh — аварийно: Noise выключен, вход по токену.
# Снять: sudo scripts/secure_recovery.sh --undo
[Service]
Environment=SECURE_CHANNEL=off
CONF
    chmod 644 "$DROPIN"
    echo "Записано: $DROPIN (SECURE_CHANNEL=off)"
fi

systemctl daemon-reload
systemctl restart "$UNIT"
sleep 3
systemctl is-active --quiet "$UNIT" && echo "${UNIT}: active" || { echo "${UNIT}: НЕ запустился"; exit 1; }
echo "Режим в журнале:"
journalctl -u "$UNIT" --since "-1 min" --no-pager | grep -E "transport=|SECURE_CHANNEL" | tail -3 || true
echo "Клиенты: VPS_WS_URL прежний, вход по WS_SECRET (старый протокол)."
