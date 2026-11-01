#!/usr/bin/env bash
# Установка SearXNG для Сакуры на VPS (Docker, порт 127.0.0.1:8888).
# Повторный запуск безопасен: секрет не пересоздаётся, контейнер обновляется.
set -euo pipefail
cd "$(dirname "$0")/../deploy/searxng"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker не найден. Установите: apt-get update && apt-get install -y docker.io docker-compose-v2" >&2
  exit 1
fi
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else echo "Нет docker compose: apt-get install -y docker-compose-v2" >&2; exit 1; fi

if [ ! -f searxng.env ]; then
  umask 077
  printf 'SEARXNG_SECRET=%s\n' "$(openssl rand -hex 32)" > searxng.env   # не выводится
  echo "Секрет создан: deploy/searxng/searxng.env (права 600)"
fi

$DC pull -q
$DC up -d

echo -n "Жду SearXNG"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:8888/search?q=wikipedia&format=json" -o /tmp/searxng_check.json 2>/dev/null; then
    n=$(python3 -c 'import json;print(len(json.load(open("/tmp/searxng_check.json")).get("results",[])))')
    rm -f /tmp/searxng_check.json
    echo; echo "SearXNG работает: тестовый запрос — $n результатов."
    echo "Добавьте в .env Сакуры: SEARXNG_URL=http://127.0.0.1:8888"
    exit 0
  fi
  echo -n "."; sleep 2
done
echo; echo "SearXNG не ответил за 60 с. Журнал: $DC logs --tail 50" >&2
exit 1
