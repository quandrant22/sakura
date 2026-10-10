# PARITY — полнота функций desktop против agent

Составлено по коду (`sakura_core/capabilities.yaml`, `agent/core/*.py`,
`agent/extension/background.js`, `agent/sakura.py`) на коммите ветки feat/desktop-rewrite.
Сгенерировано скриптом вне репозитория; правится вручную по мере переноса.

Статус «перенесено» ставится **только** при наличии теста или записанной
ручной проверки (STATE.md). Статусы: `не перенесено` / `в работе` / `перенесено`.

## Счётчики

| Перенесено | В работе | Не перенесено | Всего |
|---|---|---|---|
| 104 | 6 | 0 | 110 |

## 1. Агентные команды реестра (62)

По доменам: browser 10, app 2, close_window 1, ext 2, game_mode 2, music 18, system 6, open 1, screenshot 2, youtube 12, kettle 5, files 1.

| # | Функция (id) | legacy | Описание | Где в старом агенте | Где в новом | Тест | Статус |
|---|---|---|---|---|---|---|---|
| 1 | `browser.back` | `browser:back` | Назад | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.back] | перенесено |
| 2 | `browser.forward` | `browser:forward` | Вперёд | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.forward] | перенесено |
| 3 | `browser.scroll_down` | `browser:scroll_down` | Прокрутить вниз | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.scroll_down] | перенесено |
| 4 | `browser.scroll_up` | `browser:scroll_up` | Прокрутить вверх | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.scroll_up] | перенесено |
| 5 | `browser.tab_close` | `browser:tab_close` | Закрыть вкладку, закрой это | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.tab_close] | перенесено |
| 6 | `browser.tab_dup` | `browser:tab_dup` | Дублировать/скопировать вкладку | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.tab_dup] | перенесено |
| 7 | `app.switch` | `switch_to_app` | Переключиться на приложение — переключись на дискорд, перейди в telegram | agent.py `switch_to_app:` → hands.py `switch_to_app` | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [app.switch] | перенесено |
| 8 | `app.switch_open` | `` | Открыть установленное приложение — открой дискорд, покажи стим (не: погода, сайты, задачи) | сервер (capabilities/system.py) шлёт `switch_to_app:<имя>` → hands.py `switch_to_app` | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [app.switch_open] | перенесено |
| 9 | `browser.tab_new` | `browser:tab_new` | Новая вкладка, открыть новую | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.tab_new] | перенесено |
| 10 | `browser.tab_next` | `browser:tab_next` | Следующая вкладка | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.tab_next] | перенесено |
| 11 | `browser.tab_prev` | `browser:tab_prev` | Предыдущая вкладка | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.tab_prev] | перенесено |
| 12 | `browser.tab_reload` | `browser:tab_reload` | Обновить страницу, перезагрузи | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [browser.tab_reload] | перенесено |
| 13 | `close_window.браузер` | `close_window:браузер` | Закрыть окно браузера | agent.py `_legacy_action` → hands.py `close_window` | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [close_window.браузер] | перенесено |
| 14 | `ext.page_content` | `ext:page_content` | Что на странице, прочитай страницу | agent.py `ext:` → extension_server `send_command` → background.js | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [ext.page_content] | перенесено |
| 15 | `ext.page_content_youtube` | `ext:page_content_youtube` | Что на ютубе, что за видео | agent.py `ext:` → extension_server `send_command` → background.js | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [ext.page_content_youtube] | перенесено |
| 16 | `game_mode.off` | `game_mode:off` | Игровой режим выключить | agent.py `_run_command` (`game_mode:on/off`) → hearing/overlay | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [game_mode.off] | перенесено |
| 17 | `game_mode.on` | `game_mode:on` | Игровой режим включить | agent.py `_run_command` (`game_mode:on/off`) → hearing/overlay | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [game_mode.on] | перенесено |
| 18 | `music.dislike` | `music:dislike` | Дизлайкнуть трек | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.dislike] | перенесено |
| 19 | `music.history` | `music_history` | История, плейлисты, любимые | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.history] | перенесено |
| 20 | `music.like` | `music:like` | Лайкнуть трек (не видео) | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.like] | перенесено |
| 21 | `music.liked_tracks` | `music_liked_tracks` | История, плейлисты, любимые | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.liked_tracks] | перенесено |
| 22 | `music.mute` | `music:mute` | Список/пауза звука | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.mute] | перенесено |
| 23 | `music.next` | `music:next` | Следующий трек/песня | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.next] | перенесено |
| 24 | `music.now_playing` | `music:now_playing` | Что играет, текущий трек | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.now_playing] | перенесено |
| 25 | `music.play_pause` | `music_play_pause` | Пауза, стоп, продолжить воспроизведение | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.play_pause] | перенесено |
| 26 | `music.playlists` | `music_playlists` | История, плейлисты, любимые | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.playlists] | перенесено |
| 27 | `music.podcasts` | `music:podcasts` | Подкасты | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.podcasts] | перенесено |
| 28 | `music.prev` | `music:prev` | Предыдущий трек/песня | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.prev] | перенесено |
| 29 | `music.repeat` | `music:repeat` | Повтор трека/повторить плейлист | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.repeat] | перенесено |
| 30 | `music.seek_back` | `music:seek_back` | Перемотать вперёд/назад (10с) | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.seek_back] | перенесено |
| 31 | `music.seek_forward` | `music:seek_forward` | Перемотать вперёд/назад (10с) | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.seek_forward] | перенесено |
| 32 | `music.shuffle` | `music:shuffle` | Перемешать, случайный порядок | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.shuffle] | перенесено |
| 33 | `music.volume_down` | `music:volume_down` | Громче/тише (без числа) | agent.py перехват `music.volume_down` → hands.py `nudge_volume(-N)` (VOLUME_STEP) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.volume_down] | перенесено |
| 34 | `system.volume` | `volume` | Установить громкость | agent.py фолбэк `volume:<arg>` → hands.py `set_volume` | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [system.volume] | перенесено |
| 35 | `music.volume_up` | `music:volume_up` | Громче/тише (без числа) | agent.py перехват `music.volume_up` → hands.py `nudge_volume(+N)` (VOLUME_STEP) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.volume_up] | перенесено |
| 36 | `music.wave` | `music:wave` | Моя волна | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [music.wave] | перенесено |
| 37 | `open.app` | `open_app` | Запустить/включить/поставить/врубить музыку — любая просьба начать воспроизведение музыки | hands.py `open_app` (меню «Пуск», Steam, игровые папки, apps_cache.json) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [open.app] | перенесено |
| 38 | `screenshot.describe` | `screenshot:describe` | CHECK | agent.py `screenshot.describe` → снимок + отправка на сервер | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [screenshot.describe] | перенесено |
| 39 | `screenshot.run` | `screenshot` | Скриншот | hands.py `take_screenshot` (JPEG, вписать в 1280, качество 70) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [screenshot.run] | перенесено |
| 40 | `system.restart` | `system:restart` | Перезагрузить компьютер | agent.py → `system:restart`, но в hands.py **нет ветки restart** («неизвестная системная команда») — пробел старого агента | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [system.restart] | перенесено |
| 41 | `system.shutdown` | `system:shutdown` | Выключить компьютер | agent.py `_legacy_action` → hands.py `execute_command` (`verb == "system"`) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [system.shutdown] | перенесено |
| 42 | `system.shutdown_cancel` | `system:shutdown_cancel` | Отмена выключения компьютера | agent.py `_legacy_action` → hands.py `execute_command` (`verb == "system"`) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [system.shutdown_cancel] | перенесено |
| 43 | `system.lock` | `system:lock` | Заблокировать компьютер | agent.py `_legacy_action` → hands.py `execute_command` (`verb == "system"`) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [system.lock] | перенесено |
| 44 | `system.sleep` | `system:sleep` | Отправить компьютер в сон | agent.py `_legacy_action` → hands.py `execute_command` (`verb == "system"`) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [system.sleep] | перенесено |
| 45 | `youtube.forward` | `youtube_forward` | Перемотать вперёд | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.forward] | перенесено |
| 46 | `youtube.fullscreen` | `youtube_fullscreen` | Полный экран | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.fullscreen] | перенесено |
| 47 | `youtube.like` | `youtube_like` | Лайк видео на YouTube | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.like] | перенесено |
| 48 | `youtube.mini` | `youtube_mini` | Мини-плеер | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.mini] | перенесено |
| 49 | `youtube.next` | `youtube_next` | Следующее видео на YouTube | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.next] | перенесено |
| 50 | `youtube.pause` | `youtube_pause` | Пауза/стоп/воспроизведение на YouTube | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.pause] | перенесено |
| 51 | `youtube.rewind` | `youtube_rewind` | Перемотать назад | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.rewind] | перенесено |
| 52 | `youtube.speed_down` | `youtube_speed_down` | Скорость воспроизведения медленнее | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.speed_down] | перенесено |
| 53 | `youtube.speed_up` | `youtube_speed_up` | Скорость воспроизведения быстрее | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.speed_up] | перенесено |
| 54 | `youtube.sub_toggle` | `youtube_sub_toggle` | Субтитры | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.sub_toggle] | перенесено |
| 55 | `youtube.theater` | `youtube_theater` | Театральный режим | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.theater] | перенесено |
| 56 | `youtube.trending` | `youtube_trending` | Популярное на YouTube | agent.py `youtube_trending` (открыть URL) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [youtube.trending] | перенесено |
| 57 | `kettle.boil` | `kettle:boil` | Вскипятить чайник | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [kettle.boil] | перенесено |
| 58 | `kettle.off` | `kettle:off` | Выключить чайник | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [kettle.off] | перенесено |
| 59 | `kettle.status` | `kettle:status` | Статус чайника | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [kettle.status] | перенесено |
| 60 | `kettle.heat` | `kettle:heat` | Нагреть воду до заданной температуры | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [kettle.heat] | перенесено |
| 61 | `kettle.boil_heat` | `kettle:boil_heat` | Вскипятить и держать температуру | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [kettle.boil_heat] | перенесено |
| 62 | `files.open` | `open_file` | Найти и открыть файл | hands.py `open_file` → file_index.py `FileIndex` | тот же путь в desktop/core (WinAPI — platform.windows) | test_command_parity.py [files.open] | перенесено |

## 2. Остальные функции (48)

| # | Группа | Функция | Где в старом агенте | Где в новом | Тест | Статус |
|---|---|---|---|---|---|---|
| 1 | Голос | Слово «Сакура» (Vosk small, vosk-model-small-ru-0.22) | hearing.py `Hearing`, `_get_shared_model` | core/hearing.py | — (нужна ручная голосовая проверка) | в работе |
| 2 | Голос | Распознавание GigaAM v3_e2e_ctc, запасная цепочка v2_ctc → Vosk | hearing.py `_get_gigaam_model`, `_load_gigaam_one`, `SpeechRecognizer` | core/hearing.py | agent_port/test_gigaam_v3.py, test_gigaam_stt.py | перенесено |
| 3 | Голос | Постобработка текста (`_post_process`: пунктуация, регистр, частые ошибки) | hearing.py `_post_process`, `_add_smart_punctuation`, `_fix_common_errors` | core/hearing.py | agent_port/test_punctuation.py, test_stt_e2e_text.py | перенесено |
| 4 | Голос | VAD (Silero), конец фразы VAD_END_SILENCE / VAD_END_SILENCE_SHORT / VAD_SHORT_UTTER_SEC | hearing.py `SileroVAD`, `_end_silence_for` | core/hearing.py | agent_port/test_vad_short.py | перенесено |
| 5 | Голос | Окно дослушивания и режим диалога | hearing.py `Hearing` (listen после ответа), agent.py `_idle_after_playback` | core/hearing.py, core/agent.py | agent_port/test_agent_state.py (followup) | перенесено |
| 6 | Голос | Закладки («запомни это») | hearing.py `_bookmark_content` | core/hearing.py | agent_port/test_stt_e2e_text.py (bookmark) | перенесено |
| 7 | Голос | Эмоция голоса (анализ и применение) | hearing.py `analyze_voice_emotion`, `apply_voice_emotion` | core/hearing.py | test_core_recv.py::test_voice_emotion_* | перенесено |
| 8 | Голос | Метки [timeline] (wake → send) | agent.py `send_threadsafe` `_log_timeline` | core/agent.py | agent_port/test_stage0_metrics.py | перенесено |
| 9 | Голос | Плеер озвучки: бинарные чанки, счётчик разрывов, PLAYER_PREROLL_MS | voice.py `Player`, `decode_binary_chunk` | core/voice.py | agent_port/test_player_underrun.py, test_player_drain.py | перенесено |
| 10 | Голос | Выбор устройства вывода (AUDIO_OUTPUT_DEVICE) | voice.py `find_output_device`, `list_output_devices` | core/voice.py | test_core_misc.py::test_list_output_devices_marks_default | перенесено |
| 11 | Голос | Перебивание («стоп»), stop_speaking | hearing.py + voice.py `Player.flush` | core/voice.py, core/service.py (stop_speaking) | test_service.py::test_commands (stop_speaking); голосовое «стоп» — ручная проверка | в работе |
| 12 | Голос | Возврат в idle по tts_end и страховки (stall) | agent.py `_idle_after_playback`, presence.py `Watchdog` | core/agent.py, core/presence.py | agent_port/test_agent_state.py | перенесено |
| 13 | Сервер | WebSocket к VPS: register, ping/heartbeat, переподключение с backoff | agent.py `run`, `_heartbeat`, `_payload` | core/agent.py + core/server_link.py (proto 2) | test_server_link.py; ручная проверка на мок-сервере (STATE.md, 2026-10-10) | перенесено |
| 14 | Сервер | Outbox — очередь исходящих при обрыве | outbox.py `Outbox`, `log_send_result` | core/outbox.py | agent_port/test_outbox.py | перенесено |
| 15 | Сервер | Обработка command → command_result | agent.py `_recv_loop`, `_run_command` | core/agent.py | test_command_parity.py | перенесено |
| 16 | Сервер | reply, mood_update, context_transfer | agent.py `_recv_loop` | core/agent.py | test_core_recv.py::test_reply_mood_and_context_transfer | перенесено |
| 17 | Сервер | apps_list после подключения | agent.py `run` → hands.py `scan_apps` | core/agent.py | ручная проверка на мок-сервере (лог «Приложений: 160», STATE.md) | перенесено |
| 18 | Сервер | screen_context (анализ экрана) | agent.py `_screen_analysis_loop` | core/agent.py `_screen_analysis_loop` | — | в работе |
| 19 | Сервер | Требование WS_TOKEN (без него не стартует) | config.py, sakura.py | core/config.py, core/agent.py | agent_port/test_ws_token_required.py | перенесено |
| 20 | Расширение | extension_server: порты 8766–8769, проверка Origin и SAKURA_EXTENSION_ID | extension_server.py `_allowed_origins`, `_origin_allowed`, `run_forever` | core/extension_server.py | agent_port/test_extension_server.py | перенесено |
| 21 | Расширение | Все 76 обработчиков background.js (tabs, page_*, youtube_*, bookmarks, history, downloads, zoom…) | extension/background.js | agent/extension/background.js (общий) | agent_port/test_extension_actions.py | перенесено |
| 22 | Расширение | page_content_youtube | extension/background.js | agent/extension/background.js (общий) | agent_port/test_extension_actions.py | перенесено |
| 23 | Расширение | Защита page_fill (пароли, платёжные поля) | extension/background.js | agent/extension/background.js (общий) | agent_port/test_extension_actions.py | перенесено |
| 24 | Присутствие | Heartbeat: CPU, RAM, температуры, GPU, диск | presence.py `get_extended_system_info`, `_collect_system_info`, eyes.py `get_system_info` | core/presence.py, core/eyes.py | agent_port/test_presence_cache.py | перенесено |
| 25 | Присутствие | Активное окно и время в нём | eyes.py `get_active_window`, agent.py `_payload` | core/eyes.py | test_core_recv.py::test_active_window_title | перенесено |
| 26 | Присутствие | Уровень активности (мышь/клавиатура) | presence.py `ActivityWatcher`, `get_activity_level` | core/presence.py | test_core_recv.py::test_activity_* | перенесено |
| 27 | Присутствие | Детектор игр и игровой режим | agent.py `game_mode:*`, settings.py, hearing.py | core/agent.py, core/hearing.py | test_command_parity.py (game_mode.*), test_overlay_adapter.py | перенесено |
| 28 | Присутствие | orb_arrival/orb_departure с защитой по вводу, OVERLAY_* настройки | agent.py `mood_update`, idle.py, ui/overlay.py `animate_departure` | core/agent.py + platform.windows.idle_seconds; оверлей через desktop/overlay | agent_port/test_idle.py, test_overlay_adapter.py, agent/tests/test_overlay_departure.py | перенесено |
| 29 | Присутствие | Локальное настроение (трек, активность, температура) | local_mood.py `LocalMood` | core/local_mood.py | test_core_misc.py::test_local_mood_params_shape_and_bounds | перенесено |
| 30 | Приложения | Сканирование меню «Пуск», Steam, игровых папок (GAME_DIRS) | hands.py `_scan_start_menu`, `_scan_steam`, `_scan_game_dirs`, `scan_apps` | core/hands.py (+ platform.steam_path) | agent_port/test_hands.py | перенесено |
| 31 | Приложения | apps_cache.json, запоминание приложения (remember_app) | hands.py `_load_apps_cache`, `_save_apps_cache`, `remember_app` | core/hands.py (данные в DATA_DIR) | agent_port/test_hands.py | перенесено |
| 32 | Приложения | Индекс файлов и поиск/открытие | file_index.py `FileIndex`, hands.py `find_file`, `open_file` | core/file_index.py, core/hands.py | agent_port/test_hands.py; test_command_parity.py (files.open) | перенесено |
| 33 | Приложения | Локальные голосовые команды (реестр, 36 встроенных + пакеты) | commands.py `CommandRegistry`, hands.py `match_voice_command` | core/commands.py, core/command_packs/ | agent_port/test_protocol_commands.py, test_cp1251.py | перенесено |
| 34 | Приложения | Примитивы hotkey, type_text, focus_window, powershell | hands.py `hotkey`, `type_text`, `focus_window`, `powershell` | core/hands.py | test_command_parity.py, agent_port/test_hands.py, test_browser_controls.py | перенесено |
| 35 | Музыка | SMTC: текущий трек и управление | music.py `_smtc_get_info`, `_smtc_control` | core/music.py | test_music.py (music_command поверх подменённого SMTC); сам winsdk — без теста | в работе |
| 36 | Музыка | Яндекс.Музыка (приложение): волна, плейлисты, лайки через окно | yamusic_app.py | core/yamusic_app.py | test_music.py::test_yamusic_* | перенесено |
| 37 | Музыка | Лайки/история/плейлисты через API (YANDEX_MUSIC_TOKEN) | music.py `_ym_*` | core/music.py | test_music.py (лайк/дизлайк); история и плейлисты — без теста | в работе |
| 38 | Музыка | music_listener — системный звук для эквалайзера | music_listener.py | core/music_listener.py → событие audio_level | agent_port/test_music_listener.py | перенесено |
| 39 | Прочее | Скриншоты (JPEG 1280, качество 70) | hands.py `take_screenshot`, `_fit_for_vision` | core/hands.py | agent_port/test_screenshot_resize.py | перенесено |
| 40 | Прочее | Чайник по BLE (ключ, статус, нагрев, наблюдение) | kettle.py `KettleClient`, agent.py `_kettle_watch` | core/kettle.py | test_command_parity.py (kettle.* → kettle_command) | перенесено |
| 41 | Прочее | Уведомления (show_notification) | ui/overlay.py `show_notification` | событие notify → оверлей add_system_message | test_service.py::test_bus_events_mapped; show_notification не подключён | в работе |
| 42 | Прочее | exception_hooks | exception_hooks.py `install_exception_hooks` | core/exception_hooks.py | agent_port/test_exception_hooks.py | перенесено |
| 43 | Прочее | faulthandler (crash.log) и логи с ротацией (2 МБ × 5) | sakura.py | core/__main__.py | test_main.py::test_setup_logging_rotating | перенесено |
| 44 | Прочее | dep_check — проверка критичных пакетов | dep_check.py `check_critical_packages` | core/dep_check.py | test_core_misc.py::test_dep_check_logs_missing | перенесено |
| 45 | Прочее | Шина событий, фоновые задачи | events.py `EventBus`, tasks.py `spawn` | core/events.py, core/tasks.py | test_core_misc.py::test_event_bus_*, test_tasks_* | перенесено |
| 46 | Прочее | Настройки (settings.json) | settings.py `Settings` | core/settings.py (+ ui_settings.json в DATA_DIR) | test_core_misc.py::test_settings_persist | перенесено |
| 47 | Прочее | Переменные .env (DEVICE_ID, WS_TOKEN, VPS_WS_URL и ещё ~40 из config.py) | config.py | core/config.py (SAKURA_ENV_FILE → desktop/.env → agent/.env) | test_core_misc.py::test_config_* | перенесено |
| 48 | Прочее | Оверлей PyQt6 (сфера, панель, транскрипт, палитра) | ui/overlay.py | agent/ui/overlay.py через desktop/overlay/adapter.py | test_overlay_adapter.py | перенесено |

## Замечания

- Найдено тестом полноты по проводу сервера (`tests/fixtures/agent_wire_actions.json`) и исправлено
  в desktop/core (в agent/ не исправлялось):
  - `system.restart` — в старом `hands.py` нет ветки `restart` → теперь `Platform.power("restart")`;
  - `system.shutdown_cancel` — `_legacy_action` не переводил в `system:shutdown_cancel`;
  - `browser.tab_reload` без расширения — запасной путь знал только `reload`.
- WinAPI (`windll`, `winreg`) вынесен в `core/platform/windows.py` (тест `test_no_windll_outside_platform`).
  `win32gui`/`pycaw`/`winsdk` в hands, browser, eyes, music, yamusic_app пока вне платформы — перенос продолжается.
- Тестов старого агента: 186 (`cd agent; pytest tests -q`). Тестов ядра desktop — см. итог pytest в STATE.md.
