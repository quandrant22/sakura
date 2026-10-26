# Решения Android-клиента (feat/mobile-android)

Неясности задачи решаются осторожным вариантом; здесь — что выбрано и почему.

| № | решение | почему |
|---|---|---|
| D1 | `androidx.core:core` 1.18.0 (не 1.19.1) и OkHttp 5.3.2 (не 5.5.1) | 1.19.x и `okhttp-android` 5.5.x требуют compileSdk 37 (`checkAarMetadata`), а задача фиксирует compileSdk 36 |
| D2 | Тестовые зависимости сверх списка: Robolectric, `androidx.test:core`, OkHttp `mockwebserver3`, `org.json:json` | задача требует JUnit/Robolectric-тестов и мока на MockWebServer; `org.json` — настоящая реализация для чистых JVM-тестов (в android.jar только заглушки) |
| D3 | `lifecycle-livedata` и `lifecycle-viewmodel` входят в «lifecycle» из списка зависимостей | состояние экранов без своих Rx/корутин |
| D4 | Kotlin stdlib приходит транзитивно (OkHttp 5, androidx); прямых Kotlin-зависимостей и плагинов нет | разрешено задачей 0.1 |
| D5 | Gradle: `-Xmx1g -XX:+UseSerialGC` | на машине сборки мало commit-памяти: демон с 1,5–3 ГБ падал (hs_err: mmap failed) |
| D7 | Нормализация 8 слов — как на сервере (`securechannel/pairing.py`): разделитель всё, кроме `[a-zа-я]` после `lower()` и `ё→е` | PSK считает сервер; десктопный порт (`[^\w]\|[\d_]`) расходится на экзотических символах — берём эталон сервера |
| D8 | Счётчик rekey считает каждый отправленный кадр (и REKEY/PING/PONG), перед PING/PONG тоже проверяется rekey | так делает `securechannel/channel.py`; иначе транскрипты расходятся побайтно |
| D9 | Ручное спаривание (адрес + 8 слов) без `k`: подлинность сервера — по кадру PAIRED (PSK) и отпечатку, который показывается для сверки с Telegram | в ручном вводе ключа нет; §3.3 разрешает |
| D10 | Таймаут рукопожатия клиента 8 с | сервер молчит до 5 с и закрывает 4408 — ждём с запасом |
| D11 | Векторы cacophony скопированы в `app/src/test/resources/noise_vectors.json` (источник — `securechannel/vectors/`), транскрипты генерирует `tools/gen_sc_transcripts.py` из серверного пакета (`backend=lib`) | тесты мобилки не читают файлы вне `mobile/android` |
| D12 | Тестовые JVM: heap 512 МБ, SerialGC, одна форка | на машине сборки ~0,5 ГБ свободной commit-памяти |
| D13 | Outbox только в памяти процесса (не на диске) | TTL 120 с; тексты — приватные классы, на диск не пишем |
| D14 | `register`: `proto: 2`, `kind: "phone"`, `system_info: {stats: {...}}`, `input_idle_s`, `active_window: ""`; без `token` | контракт; аутентификация — ключ Noise |
| D15 | Нет `registered` за 5 с → сервер считается v1: запросы v2 сразу `unsupported`, реплики `voice_command` работают | как десктоп (PROTOCOL §1.2) |
| D16 | Связь живёт, пока открыто приложение; в фоне — только при «Всегда на связи» (foreground specialUse). При уходе в фон без него — `bye{reason:"exit"}` | приложение личное; без лишней батареи |
| D17 | Тип FGS microphone добавляется только по запросу из открытого приложения; отказ системы — остаёмся specialUse | Android 14+ запрещает microphone-FGS из фона |
| D18 | «Говорить» в уведомлении открывает приложение (`ACTION_LISTEN`) | доступ к микрофону — только при открытом приложении |
| D6 | Predictive back: `android:enableOnBackInvokedCallback="true"`; edge-to-edge — `EdgeToEdge.enable` + отступы по insets | targetSdk 36 |
