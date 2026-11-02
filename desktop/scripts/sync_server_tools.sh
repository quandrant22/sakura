#!/bin/sh
# Обновить desktop/tests/fixtures/server_tools.json из выгрузки сервера одной командой:
#   desktop/scripts/sync_server_tools.sh [ветка]        (по умолчанию origin/server/browser-step)
# Берёт tests/fixtures/server_tools.json ветки сервера (git show) байт в байт, без правок,
# и проверяет, что blob в рабочей копии совпал с серверным. Секреты не читает.
set -eu

REF="${1:-origin/server/browser-step}"
SRC="tests/fixtures/server_tools.json"
ROOT="$(git rev-parse --show-toplevel)"
DST="$ROOT/desktop/tests/fixtures/server_tools.json"

case "$REF" in
  origin/*) git -C "$ROOT" fetch --quiet origin "${REF#origin/}" ;;
esac

WANT="$(git -C "$ROOT" rev-parse "$REF:$SRC")"
git -C "$ROOT" cat-file blob "$WANT" > "$DST.tmp"
mv "$DST.tmp" "$DST"

GOT="$(git -C "$ROOT" hash-object --path "desktop/tests/fixtures/server_tools.json" "$DST")"
if [ "$GOT" != "$WANT" ]; then
  echo "server_tools.json: blob $GOT не совпал с $REF ($WANT)" >&2
  exit 1
fi
echo "server_tools.json ← $REF ($(git -C "$ROOT" rev-parse --short "$REF"), blob ${WANT%"${WANT#???????}"})"
