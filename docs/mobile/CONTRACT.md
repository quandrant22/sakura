# Контракт телефона (общий с серверной задачей server/phone)

Копия из задачи «Android-клиент Сакуры». Клиент реализован по нему и проверен на моке
(`mobile/android/app/src/test/java/app/sakura/mobile/mock/MockSakuraServer.java`). Пока сервер не выкачен,
клиент корректно показывает `unsupported`, `not_master` и `secure_channel_required`.

1. **Устройство.** `device_id=phone`, kind `phone`. Подключение только по Noise (`securechannel/1`),
   `WS_TOKEN` не используется. Master-права даются только на Noise-соединении. Активным устройством
   телефон не становится, агентные команды с телефона исполняет активный ПК.

2. **Команда на телефон.** Сервер → телефон: `{"type":"command","id","action","arg"}`, где `action` из списка:
   `phone.find`, `phone.dnd_on`, `phone.dnd_off`, `phone.alarm` (arg `HH:MM`), `phone.timer` (arg — секунды),
   `phone.flashlight` (arg `on|off`), `phone.volume` (arg 0–100), `phone.clipboard` (arg — текст),
   `phone.open_url`, `phone.open_app` (arg — название), `phone.media_play_pause`, `phone.media_next`,
   `phone.media_prev`, `phone.notify` (arg — текст).
   Ответ: `{"type":"command_result","id","ok","status":"done|noop|failed|unsupported","detail"}`.

3. **Запуск действия кнопкой.** `{"type":"action_run","request_id","action","arg"?,"device"?}` →
   `{"type":"action_started","request_id","action","id"}`. Ошибки: `bad_request`, `not_found`, `not_master`.
   Для действий питания вопрос приходит как `reply` с `kind:"confirm"`, ответ шлётся `voice_command` с текстом
   «да»/«нет» и `channel:"text"`.

4. **Без озвучки.** Поле `speak:false` в `voice_command` и `chat_send`: сервер отдаёт `reply` и `chat_message`
   без `tts_chunk`/`tts_end`.

5. **Устройство в списке.** В `devices` и `device_update` добавлены `active: bool` и
   `track: {title, artist, status, cover_url|null, ts} | null`.

6. **Камера.** `vision_request` с полем `source:"camera"`: JPEG base64, лимит как у кадра окна.

7. **Озвучка.** `tts_chunk`: base64 PCM16 mono, `sample_rate` 24000, `turn_id`; конец — `tts_end`.

## Где в клиенте

| пункт | код | тест |
|---|---|---|
| 1 | `link/SecureLink`, `proto/SakuraClient` (register `kind:"phone"`, без token) | `MockServerE2ETest.pairingByQrThenSessionAndRegister` |
| 2 | `exec/PhoneExecutor`, `exec/AndroidPhoneApis`, `exec/CommandRouter` | `PhoneExecutorTest`, `MockServerE2ETest.phoneCommandColdPath` |
| 3 | `ui/control/ControlModel`, `ui/MainActivity.showConfirm`, `voice/VoiceController.answerConfirm` | `MockServerE2ETest.actionRunAndPowerConfirm` |
| 4 | `SakuraClient.voice/chatSend(speak)`, `VoiceController.speakReplies` | `MockServerE2ETest.speakFalseHasNoTts` |
| 5 | `ui/model/Models.Device` (`active`, `track`) | `MockServerE2ETest.requestsAndDevicesWithActiveAndTrack`, `ModelsTest` |
| 6 | `vision/Vision`, `vision/WhatIsThisActivity`, `share/ShareActivity` | `M8Test.visionFitKeepsAspectAndLimit` |
| 7 | `voice/PlaybackController`, `voice/Player` (поле `audio`, как в `modules/tts_server.py`) | `PlaybackControllerTest` |
