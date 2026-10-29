# Сырой вывод ProVerif

Здесь лежит вывод ProVerif без правок, по файлу на модель. На VPS ProVerif
**не запускается** (DECISIONS V1): только на машине владельца или в CI.

## Требования

ProVerif **≥ 2.04** (проверено чтением грамматики 2.05). Установка — любой путь:

```sh
opam install proverif                        # через opam
# или из исходников: https://bblanche.gitlabpages.inria.fr/proverif/
#   proverif2.05.tar.gz, sha256 4871f53c32ab4a04669a060c4886ba5d9080496963fb980a9a62d2c429ceabc4
#   tar xzf proverif2.05.tar.gz && cd proverif2.05 && ./build -nointeract
```

## Запуск (из корня репозитория)

```sh
cd docs/security/proverif
for m in ik xxpsk3; do
  proverif -parse-only "$m.pv" || exit 1       # сначала только синтаксис
done
for m in ik xxpsk3; do
  { proverif -help 2>&1 | head -1; echo "model: $m.pv"; date -u +%FT%TZ; echo;
    /usr/bin/time -v proverif "$m.pv"; } > "results/$m.txt" 2>&1
done
grep -h "^RESULT" results/ik.txt results/xxpsk3.txt
```

Нет `/usr/bin/time` (macOS) — уберите `/usr/bin/time -v`. Файлы
`results/ik.txt` и `results/xxpsk3.txt` коммитятся как есть, без правок и
сокращений.

## Что ожидается

Ожидаемые результаты каждого запроса перечислены в шапке модели и в
[../../FORMAL.md](../../FORMAL.md) §0. «false» у Q7, Q8, Q10 (ik) и Q6, Q8,
Q9, Q10 (xxpsk3) — ожидаемые атаки и проверки достижимости. Любое другое
расхождение (true ↔ false, «cannot be proved», незавершение) модель **не
правят под ответ** — его описывают в `docs/security/FINDINGS.md`.
