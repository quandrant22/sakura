# Прогресс разработки мобильного клиента Sakura (Android)

## Задача 0: Проверка окружения и каркаса Android

- **Git**: `git version 2.55.0.windows.5`, origin = `https://github.com/quandrant22/sakura.git`, ветка `feat/mobile-android` (база `origin/master`, commit `8dc9e6cea188643c058a8a808449b33f7f129255`).
- **JDK**: OpenJDK 21.0.10 (JBR Android Studio: `C:\Program Files\Android\Android Studio\jbr`).
- **Gradle**: 9.4.1
- **AGP**: 9.2.1
- **Android SDK**: `C:\Users\MosTech\AppData\Local\Android\Sdk`
- **Установленные пакеты SDK**: `platforms;android-36`, `build-tools;36.0.0` (автоматически загружены и лицензии приняты AGP/Gradle), а также `android-36.1`, `36.1.0`, `37.0.0`. `cmdline-tools` отсутствует в дистрибутиве SDK (владельцу при необходимости установит SDK Manager в Studio).
- **Серверная часть**: передана отдельному агенту.
- **Результат сборки каркаса**: `gradlew.bat assembleDebug testDebugUnitTest` — SUCCESSFUL (38 задач выполнено, unit-тесты пройдены).
- **Коммит каркаса**: `4ee83dbc7cdcf543483589cd63ecb169504fdc7c` (`chore(mobile): каркас Android-проекта (Java, Views, minSdk 33, Groovy DSL, SDK 36)`).

## Задача 0.1: исправления каркаса

- Бэкап запрещён: `allowBackup="false"`, `fullBackupContent` и `backup_rules.xml` удалены; `data_extraction_rules.xml` исключает root/file/database/sharedpref/external для cloud-backup и device-transfer.
- Release: `minifyEnabled true` + `shrinkResources true` (R8, обфускация), правила в `app/proguard-rules.pro`; `Log.d`/`Log.v` вырезаются через `-assumenosideeffects`. Новый DSL `optimization.enable` в AGP 9.2.1 требует экспериментального флага `android.r8.gradual.support`, поэтому взят классический.
- Зависимости: `activity-ktx` → `androidx.activity:activity` 1.13.0; appcompat 1.8.0, material 1.14.0, constraintlayout 2.2.2, junit 4.13.2, ext-junit 1.3.0, espresso 3.7.0. Прямых Kotlin-зависимостей и плагинов нет.
- `gradlew.bat clean assembleDebug assembleRelease testDebugUnitTest` — BUILD SUCCESSFUL (82 задачи); release проверен с временной подписью debug-ключом, в git её нет. JDK — Android Studio JBR (`JAVA_HOME` не задан в системе).

## Уборка (задача 0.2)

- Каталог `mobile/android/memory/` удалён, не открывая файлы. Причина появления: модули сервера пишут в относительные пути (`config.py`: `KEYS_FILE = "memory/api_keys.json"`; `modules/relationship.py`: `memory/first_run.json`; `modules/fortune_cookie.py` и др.), а серверный код запускался (pytest в задаче 0) с рабочим каталогом сессии `mobile/android`. Файлы созданы 26.10 12:48–12:58. Защита: `memory/` в `mobile/android/.gitignore`; серверный код из `mobile/android` больше не запускается.

## Android-клиент

| блок | состояние |
|---|---|
| M1 каркас | зависимости: appcompat, core, recyclerview, lifecycle, constraintlayout, viewpager2, material, OkHttp, bcprov, ZXing embedded, Vosk, CameraX (+ тестовые, D2); edge-to-edge, predictive back; бэкап запрещён; `assembleDebug testDebugUnitTest` — SUCCESSFUL |
| M2 канал | `crypto/noise` (CipherState, SymmetricState, HandshakeState IK/XXpsk3 на BouncyCastle), `link` (FrameCodec, SecureChannel с rekey, SecureLink на OkHttp, Backoff 1→30 с, CloseCodes, secure_server_key), `pairing` (8 слов, PSK, QR с проверкой срока, отпечаток, PairingSession XXpsk3 со сверкой k), `keys` (X25519 под AES-GCM `sakura_wrap`); тесты: векторы cacophony, побайтные транскрипты сервера (IK, IK с rekey, XXpsk3, фрагмент > 64 КБ), кодек, нормализация, QR, wrap/unwrap — 30 passed |
| M3 протокол и служба | `proto`: SakuraClient (register/ping proto 2 каждые 30 с: battery, charging, wifi-тип, signal 0–4, input_idle_s; bye exit), RequestClient (request_id, 10 с → timeout, offline, unsupported для v1), EventBus, Outbox (voice_command/chat_send, TTL 120 с, confirm-ответы не копятся), ErrorText (дословно SERVER_FEATURES); `app`: SakuraApp, SakuraService (specialUse + microphone, «Говорить»/«Отключиться»), «Всегда на связи»; MockSakuraServer (Noise IK/XXpsk3, режимы unsupported / not_master / secure_channel_required / Noise off); сквозные тесты: спаривание QR и вручную, неверные слова, подмена ключа в QR, неизвестный ключ → 4408, ping, devices с active/track, action_run + confirm, speak:false, outbox после переподключения, ротация ключа сервера, bye — 54 passed |
| M6 визуал | закрыт 2026-10-27: снимки 5 состояний ядра × 2 темы записаны (CPU-растр, D22), `AgslUniformsTest`, `CoreShaderInstrumentedTest` (устройство). Прогон `testDebugUnitTest verifyPaparazziDebug lint assembleDebug assembleRelease` — BUILD SUCCESSFUL: 66 passed, lint 0 ошибок / 30 предупреждений |
| M4 голос | `voice`: PlaybackController (turn_id, преролл 150 мс, разрывы, stall 3 с, перебивание) + AudioTrackSink (MODE_STREAM, TRANSIENT_MAY_DUCK, системный маршрут) + Player (поток «sakura-audio»); SpeechInput (on-device ru-RU, иначе EXTRA_PREFER_OFFLINE; живой транскрипт, RMS → ядро); WakeWord (Vosk, грамматика «сакура», во время речи — только AEC или гарнитура); ModelInstaller (SHA-256, D23); VoiceController (Онлайн/Слушаю/Думаю/Говорю/Нет связи, тап/PTT с вибрацией/гарнитура, дослушивание 0–15 с, «Ответы текстом» и беззвучный режим → speak:false). Прогон `testDebugUnitTest verifyPaparazziDebug lint assembleDebug assembleRelease` — BUILD SUCCESSFUL: 81 passed, lint 0 ошибок / 26 предупреждений |
| M5 экраны | нижняя навигация (Диалог, Пульт, Сводка, Сценарии, Ещё), подэкраны со стеком «Назад», переходы 150 мс; состояния скелетон / пусто / ошибка с «Повторить» / офлайн (`StateView`, тексты — SERVER_FEATURES); Диалог: ядро и статус, history_request + «Загрузить раньше», push chat_message, пузыри (градиент / panel2, метка канала и устройства), поиск, удаление с подтверждением, экспорт через Share sheet, ввод и микрофон; Пульт: карточки ПК, мини-плеер, action_run с device, «Да/Нет» на kind:"confirm"; Сводка; Сценарии: список, запуск с журналом, удаление, конструктор «Если … То …», «Из фразы» с предпросмотром; Ещё: Память, Профиль, Голос, Безопасность (QR/8 слов, отпечаток, secure_devices, «Забыть сервер», «Всегда на связи»), Интерфейс, Разрешения, Диагностика. `tools/gen_phone_triggers.py` → `assets/phone_triggers.json`. Paparazzi: 84 снимка (все экраны × 2 темы). Прогон `testDebugUnitTest verifyPaparazziDebug lint assembleDebug assembleRelease` — BUILD SUCCESSFUL: 105 passed, lint 0 ошибок / 143 предупреждения |
| M7 исполнитель | `exec`: PhoneExecutor (14 действий контракта → command_result done/noop/failed/unsupported; нет разрешения → «нет разрешения: …» + уведомление на экран «Разрешения»), AndroidPhoneApis (USAGE_ALARM 30 с, setInterruptionFilter, AlarmClock SKIP_UI, setTorchMode, AudioManager, ClipboardManager, ACTION_VIEW, PackageManager + `<queries>`, dispatchMediaKeyEvent, канал «Сакура»), AppMatcher (нечёткий поиск), OfflineMatcher (границы слов, самый длинный триггер, аргументы), CommandRouter (холодный путь в Application). Прогон `testDebugUnitTest verifyPaparazziDebug lint assembleDebug assembleRelease` — BUILD SUCCESSFUL: 115 passed, lint 0 ошибок / 143 предупреждения |
| M8 возможности телефона | ассистент (VoiceInteractionService, панель с ядром, экран блокировки — только голос и ответ, RecognitionService-посредник), плитка быстрых настроек, виджет (статичный кадр ядра, «Говорить», 3 кнопки action_run), плавающее ядро (overlay 56dp, состояния, прилипание к краю, зона «×»), Share-target (текст → chat_send «Мастер поделился:», картинка → vision_request source:"camera"), «Что это?» (CameraX в память, JPEG 1280/q70, общий элемент ядра). Снимки: + панель ассистента и виджет (90 всего). Прогон `testDebugUnitTest verifyPaparazziDebug lint assembleDebug assembleRelease` — BUILD SUCCESSFUL: 121 passed, lint 0 ошибок / 153 предупреждения |
| M6 визуал (часть, 2026-10-26) | токены UI.md → colors/attrs/dimens, темы Theme.Sakura.Night (по умолчанию) и Theme.Sakura.Sketch; CoreFrame.java — порт coreFrame.ts (сверка с 180 кадрами `tools/export-core-frames.mjs`, допуск 1e-3, NaN/∞); CoreShading (AGSL-метаболы + та же формула на CPU), SakuraCoreView (Choreographer, fps 30/60/10, переход 250 мс, кольца 2dp, свечение, статичный кадр); Motion (пузыри 150 мс + 8dp, экраны 150 мс, тактильный отклик); тест-сканер хардкода цветов. Paparazzi 2.0.0-alpha05.1 подключён, снимки ядра не записаны: тестовой JVM не хватает памяти (см. «Блокер») |

| Документы | ARCHITECTURE.md, CONTRACT.md (копия контракта + где в коде), PARITY.md (110 строк десктопа: 20 на телефоне, 70 через пульт, 20 не применимо), UI.md, DECISIONS.md (D1–D47), RUNBOOK.md (APK, /pair, каждое phone.*, голос, подтверждение питания, ассистент, отказ неизвестному ключу) |

### Итог (2026-10-27)

- Блоки M1–M8 закрыты, каждый — полным прогоном `testDebugUnitTest verifyPaparazziDebug lint assembleDebug assembleRelease`
  (последний: 121 passed, 90 снимков, lint 0 ошибок).
- `git diff --stat origin/master...feat/mobile-android` — только `mobile/android/**` и `docs/mobile/**`.
- Живые проверки на телефоне и реальном сервере не выполнялись — RUNBOOK.md.
- Ждёт сервер (server/phone): `phone.*` в `capabilities.yaml` (тогда `tools/gen_phone_triggers.py` перейдёт на реестр,
  seed удалить — D29), `action_run`, `speak:false`, `active`/`track` в devices, `source:"camera"`.

### Блокер (2026-10-26) — снят перезагрузкой 2026-10-27

Свободной commit-памяти в системе ~0,3 ГБ из 31 ГБ (занята не процессами сборки); тестовая JVM с heap 512 МБ не стартует («Could not reserve enough space for object heap»), периодически не создаются и простые процессы. Нужна перезагрузка машины или больший файл подкачки.
