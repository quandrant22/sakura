# Архитектура Android-клиента Сакуры

Тонкий клиент: своей памяти, сценариев и LLM нет. Локально — только ключи (`files/keys/`), настройки
(SharedPreferences) и outbox (в памяти). Java 17, Views + XML, без Kotlin и Compose.

## Слои

```
 ui/ (вкладки, экраны-binder'ы, ViewModel)      assistant/ tile/ widget/ overlay/ share/ vision/
            │ LiveData                                    │
 voice/ (распознавание, плеер, «Сакура»)  ── VoiceController ── exec/ (PhoneExecutor, офлайн-путь)
            │                                             │
 proto/ (SakuraClient: register/ping, RequestClient, EventBus, Outbox)
            │ JSON приложения
 link/ (SecureLink: Noise IK на OkHttp WebSocket, кадры «SK», rekey, переподключение)
            │
 crypto/noise/ (CipherState, SymmetricState, HandshakeState — BouncyCastle)   keys/ (X25519 под Keystore)
```

| пакет | что внутри |
|---|---|
| `crypto.noise` | Noise rev 34: IK и XXpsk3, 25519_ChaChaPoly_BLAKE2s; примитивы — только BouncyCastle |
| `link` | `FrameCodec` (SK, ver 1, u32 BE ≤ 65535, строгая длина; фрагментация ≤ 64 × 65517, 2 МиБ), `SecureChannel` (nonce, rekey по 10 000 кадров / 3600 с), `SecureLink` (IK_INIT/IK_RESP, PING→PONG, CLOSE, `secure_server_key`), `Backoff` 1→30 с ±20 %, `CloseCodes` |
| `pairing` | 8 слов → PSK (нормализация сервера), QR `sakura-pair://1` со сроком, отпечаток §8.1, `PairingSession` (XXpsk3, сверка k до XX_3, PAIRED) |
| `keys` | `DeviceKeyStore`: `device.key` = AES-GCM(`sakura_wrap` в Android Keystore, X25519), `server.json`; «Забыть сервер» |
| `proto` | `SakuraClient` (register/ping proto 2 с `system_info.stats` и `input_idle_s`, bye, outbox), `RequestClient` (request_id, 10 с, offline/unsupported), `EventBus`, `ErrorText` (тексты SERVER_FEATURES) |
| `app` | `SakuraApp` (одна связь на процесс), `SakuraService` (FGS specialUse + microphone), `Settings`, `Permissions`, `AndroidDeviceInfo` |
| `voice` | `PlaybackController` + `AudioTrackSink` (24 кГц, преролл 150 мс, stall 3 с, TRANSIENT_MAY_DUCK), `SpeechInput` (on-device ru-RU), `WakeWord` (Vosk), `ModelInstaller` (SHA-256), `FollowUp`, `VoiceController` |
| `core` | `CoreFrame` (порт coreFrame.ts), `CoreShading` (AGSL + та же формула на CPU), `SakuraCoreView` |
| `exec` | `PhoneExecutor` (phone.* → command_result), `AndroidPhoneApis`, `AppMatcher`, `OfflineMatcher`, `CommandRouter` |
| `ui` | `MainActivity` (5 вкладок, стек подэкранов, общий диалог confirm), экраны `*Screen` (разметка + render) и `*Model` (ViewModel) |
| `assistant`, `tile`, `widget`, `overlay`, `share`, `vision` | M8: ассистент, плитка, виджет, плавающее ядро, Share-target, «Что это?» |

## Потоки

| поток | что |
|---|---|
| main | UI, SpeechRecognizer, Vosk-колбэки, LiveData |
| `sakura-net` (один, ScheduledExecutor) | SecureLink/SakuraClient: рукопожатие, шифрование, разбор, таймеры, колбэки запросов и шины |
| OkHttp | чтение сокета (сразу передаёт в `sakura-net` под блокировкой SecureLink) |
| `sakura-audio` (THREAD_PRIORITY_AUDIO) | декод base64, AudioTrack, тик 50 мс |
| `sakura-vosk` | загрузка модели и распознавание слова |
| `sakura-exec` | исполнение phone.* (холодный путь не ждёт UI) |
| `sakura-model`, `sakura-vision`, `sakura-share` | загрузка модели, сжатие кадра |

Сеть, криптография, аудио и Vosk — вне main thread. В `onDraw` ядра нет аллокаций (буферы — в `onSizeChanged`).

## Холодный путь команды

`SecureLink` → `SakuraClient.onMessage` → `EventBus` «command» → `CommandRouter` (подписан в `SakuraApp.onCreate`) →
`PhoneExecutor` на `sakura-exec` → `client.sendRaw(command_result)`. Не зависит от Activity, темы, анимаций и
озвучки; работает и при закрытом приложении, если связь держит «Всегда на связи».

## Жизненный цикл связи

Связь поднимается, когда видна любая Activity, и опускается (`bye{reason:"exit"}`) при уходе в фон — кроме режима
«Всегда на связи» (foreground-служба specialUse). Панель ассистента, кнопка виджета и Share поднимают связь на
время действия (D42, D44, D47).

## Безопасность и журнал

- Ключи, PSK, 8 слов, тела `chat_*`/`memory_*`/`profile_*`/`history_*` и кадры изображений в logcat не пишутся
  (в коде нет `Log` по ним; release вырезает `Log.d`/`Log.v`).
- Бэкап и перенос данных запрещены (`allowBackup=false`, `data_extraction_rules` исключают всё).
- Память не кэшируется (ViewModel фрагмента), outbox — только в памяти.

## Тесты

| вид | что |
|---|---|
| JUnit (JVM) | векторы Noise, побайтные транскрипты сервера, кодек, нормализация, QR, wrap/unwrap, CoreFrame (180 кадров), outbox, запросы, плеер, исполнитель, офлайн-матчер, модели, тексты ошибок |
| сквозные с `MockSakuraServer` | спаривание (QR, вручную, неверные слова, подмена ключа), 4408, ping, devices active/track, action_run + confirm, speak:false, outbox, ротация ключа, bye, команды phone.*, режимы unsupported / not_master / secure_channel_required |
| Paparazzi | 90 снимков: все экраны × 2 темы × состояния, 5 состояний ядра, панель ассистента, виджет |
| androidTest | компиляция и отрисовка AGSL на устройстве (`CoreShaderInstrumentedTest`, по RUNBOOK) |

Команда: `gradlew.bat testDebugUnitTest verifyPaparazziDebug lint assembleDebug assembleRelease`.

## Генераторы (`mobile/android/tools/`)

| файл | что | окружение |
|---|---|---|
| `gen_sc_transcripts.py` | транскрипты IK/XXpsk3 из серверного `securechannel/` | `tools/.venv` (3.11): cryptography, noiseprotocol |
| `export-core-frames.mjs` | 180 эталонных кадров из `coreFrame.ts` (через `git show`) | Node ≥ 22.18 |
| `gen_phone_triggers.py` | `assets/phone_triggers.json` из `capabilities.yaml` (пока — `phone_triggers.seed.yaml`) | `tools/.venv` |
