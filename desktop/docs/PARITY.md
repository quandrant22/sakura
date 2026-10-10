# PARITY — полнота функций desktop против agent

Составлено по коду (`sakura_core/capabilities.yaml`, `agent/core/*.py`,
`agent/extension/background.js`, `agent/sakura.py`) на коммите ветки feat/desktop-rewrite.
Сгенерировано скриптом вне репозитория; правится вручную по мере переноса.

Статус «перенесено» ставится **только** при наличии теста или записанной
ручной проверки (STATE.md). Статусы: `не перенесено` / `в работе` / `перенесено`.

## Счётчики

| Перенесено | В работе | Не перенесено | Всего |
|---|---|---|---|
| 0 | 0 | 110 | 110 |

## 1. Агентные команды реестра (62)

По доменам: browser 10, app 2, close_window 1, ext 2, game_mode 2, music 18, system 6, open 1, screenshot 2, youtube 12, kettle 5, files 1.

| # | Функция (id) | legacy | Описание | Где в старом агенте | Где в новом | Тест | Статус |
|---|---|---|---|---|---|---|---|
| 1 | `browser.back` | `browser:back` | Назад | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 2 | `browser.forward` | `browser:forward` | Вперёд | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 3 | `browser.scroll_down` | `browser:scroll_down` | Прокрутить вниз | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 4 | `browser.scroll_up` | `browser:scroll_up` | Прокрутить вверх | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 5 | `browser.tab_close` | `browser:tab_close` | Закрыть вкладку, закрой это | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 6 | `browser.tab_dup` | `browser:tab_dup` | Дублировать/скопировать вкладку | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 7 | `app.switch` | `switch_to_app` | Переключиться на приложение — переключись на дискорд, перейди в telegram | agent.py `switch_to_app:` → hands.py `switch_to_app` | — | — | не перенесено |
| 8 | `app.switch_open` | `` | Открыть установленное приложение — открой дискорд, покажи стим (не: погода, сайты, задачи) | сервер (capabilities/system.py) шлёт `switch_to_app:<имя>` → hands.py `switch_to_app` | — | — | не перенесено |
| 9 | `browser.tab_new` | `browser:tab_new` | Новая вкладка, открыть новую | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 10 | `browser.tab_next` | `browser:tab_next` | Следующая вкладка | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 11 | `browser.tab_prev` | `browser:tab_prev` | Предыдущая вкладка | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 12 | `browser.tab_reload` | `browser:tab_reload` | Обновить страницу, перезагрузи | agent.py `_legacy_action` → `browser:<verb>` → hands.py `execute_command` (`verb == "browser"`: расширение, иначе browser.py хоткеи) | — | — | не перенесено |
| 13 | `close_window.браузер` | `close_window:браузер` | Закрыть окно браузера | agent.py `_legacy_action` → hands.py `close_window` | — | — | не перенесено |
| 14 | `ext.page_content` | `ext:page_content` | Что на странице, прочитай страницу | agent.py `ext:` → extension_server `send_command` → background.js | — | — | не перенесено |
| 15 | `ext.page_content_youtube` | `ext:page_content_youtube` | Что на ютубе, что за видео | agent.py `ext:` → extension_server `send_command` → background.js | — | — | не перенесено |
| 16 | `game_mode.off` | `game_mode:off` | Игровой режим выключить | agent.py `_run_command` (`game_mode:on/off`) → hearing/overlay | — | — | не перенесено |
| 17 | `game_mode.on` | `game_mode:on` | Игровой режим включить | agent.py `_run_command` (`game_mode:on/off`) → hearing/overlay | — | — | не перенесено |
| 18 | `music.dislike` | `music:dislike` | Дизлайкнуть трек | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 19 | `music.history` | `music_history` | История, плейлисты, любимые | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 20 | `music.like` | `music:like` | Лайкнуть трек (не видео) | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 21 | `music.liked_tracks` | `music_liked_tracks` | История, плейлисты, любимые | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 22 | `music.mute` | `music:mute` | Список/пауза звука | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 23 | `music.next` | `music:next` | Следующий трек/песня | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 24 | `music.now_playing` | `music:now_playing` | Что играет, текущий трек | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 25 | `music.play_pause` | `music_play_pause` | Пауза, стоп, продолжить воспроизведение | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 26 | `music.playlists` | `music_playlists` | История, плейлисты, любимые | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 27 | `music.podcasts` | `music:podcasts` | Подкасты | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 28 | `music.prev` | `music:prev` | Предыдущий трек/песня | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 29 | `music.repeat` | `music:repeat` | Повтор трека/повторить плейлист | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 30 | `music.seek_back` | `music:seek_back` | Перемотать вперёд/назад (10с) | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 31 | `music.seek_forward` | `music:seek_forward` | Перемотать вперёд/назад (10с) | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 32 | `music.shuffle` | `music:shuffle` | Перемешать, случайный порядок | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 33 | `music.volume_down` | `music:volume_down` | Громче/тише (без числа) | agent.py перехват `music.volume_down` → hands.py `nudge_volume(-N)` (VOLUME_STEP) | — | — | не перенесено |
| 34 | `system.volume` | `volume` | Установить громкость | agent.py фолбэк `volume:<arg>` → hands.py `set_volume` | — | — | не перенесено |
| 35 | `music.volume_up` | `music:volume_up` | Громче/тише (без числа) | agent.py перехват `music.volume_up` → hands.py `nudge_volume(+N)` (VOLUME_STEP) | — | — | не перенесено |
| 36 | `music.wave` | `music:wave` | Моя волна | agent.py `_music_canonical` → music.py (SMTC/Я.Музыка API) / yamusic_app.py / browser.py медиаклавиши | — | — | не перенесено |
| 37 | `open.app` | `open_app` | Запустить/включить/поставить/врубить музыку — любая просьба начать воспроизведение музыки | hands.py `open_app` (меню «Пуск», Steam, игровые папки, apps_cache.json) | — | — | не перенесено |
| 38 | `screenshot.describe` | `screenshot:describe` | CHECK | agent.py `screenshot.describe` → снимок + отправка на сервер | — | — | не перенесено |
| 39 | `screenshot.run` | `screenshot` | Скриншот | hands.py `take_screenshot` (JPEG, вписать в 1280, качество 70) | — | — | не перенесено |
| 40 | `system.restart` | `system:restart` | Перезагрузить компьютер | agent.py → `system:restart`, но в hands.py **нет ветки restart** («неизвестная системная команда») — пробел старого агента | — | — | не перенесено |
| 41 | `system.shutdown` | `system:shutdown` | Выключить компьютер | agent.py `_legacy_action` → hands.py `execute_command` (`verb == "system"`) | — | — | не перенесено |
| 42 | `system.shutdown_cancel` | `system:shutdown_cancel` | Отмена выключения компьютера | agent.py `_legacy_action` → hands.py `execute_command` (`verb == "system"`) | — | — | не перенесено |
| 43 | `system.lock` | `system:lock` | Заблокировать компьютер | agent.py `_legacy_action` → hands.py `execute_command` (`verb == "system"`) | — | — | не перенесено |
| 44 | `system.sleep` | `system:sleep` | Отправить компьютер в сон | agent.py `_legacy_action` → hands.py `execute_command` (`verb == "system"`) | — | — | не перенесено |
| 45 | `youtube.forward` | `youtube_forward` | Перемотать вперёд | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 46 | `youtube.fullscreen` | `youtube_fullscreen` | Полный экран | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 47 | `youtube.like` | `youtube_like` | Лайк видео на YouTube | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 48 | `youtube.mini` | `youtube_mini` | Мини-плеер | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 49 | `youtube.next` | `youtube_next` | Следующее видео на YouTube | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 50 | `youtube.pause` | `youtube_pause` | Пауза/стоп/воспроизведение на YouTube | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 51 | `youtube.rewind` | `youtube_rewind` | Перемотать назад | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 52 | `youtube.speed_down` | `youtube_speed_down` | Скорость воспроизведения медленнее | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 53 | `youtube.speed_up` | `youtube_speed_up` | Скорость воспроизведения быстрее | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 54 | `youtube.sub_toggle` | `youtube_sub_toggle` | Субтитры | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 55 | `youtube.theater` | `youtube_theater` | Театральный режим | agent.py `youtube_*` → extension_server → background.js (иначе browser.py) | — | — | не перенесено |
| 56 | `youtube.trending` | `youtube_trending` | Популярное на YouTube | agent.py `youtube_trending` (открыть URL) | — | — | не перенесено |
| 57 | `kettle.boil` | `kettle:boil` | Вскипятить чайник | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | — | — | не перенесено |
| 58 | `kettle.off` | `kettle:off` | Выключить чайник | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | — | — | не перенесено |
| 59 | `kettle.status` | `kettle:status` | Статус чайника | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | — | — | не перенесено |
| 60 | `kettle.heat` | `kettle:heat` | Нагреть воду до заданной температуры | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | — | — | не перенесено |
| 61 | `kettle.boil_heat` | `kettle:boil_heat` | Вскипятить и держать температуру | agent.py `kettle:` → kettle.py `kettle_command` (BLE) | — | — | не перенесено |
| 62 | `files.open` | `open_file` | Найти и открыть файл | hands.py `open_file` → file_index.py `FileIndex` | — | — | не перенесено |

## 2. Остальные функции (48)

| # | Группа | Функция | Где в старом агенте | Где в новом | Тест | Статус |
|---|---|---|---|---|---|---|
| 1 | Голос | Слово «Сакура» (Vosk small, vosk-model-small-ru-0.22) | hearing.py `Hearing`, `_get_shared_model` | — | — | не перенесено |
| 2 | Голос | Распознавание GigaAM v3_e2e_ctc, запасная цепочка v2_ctc → Vosk | hearing.py `_get_gigaam_model`, `_load_gigaam_one`, `SpeechRecognizer` | — | — | не перенесено |
| 3 | Голос | Постобработка текста (`_post_process`: пунктуация, регистр, частые ошибки) | hearing.py `_post_process`, `_add_smart_punctuation`, `_fix_common_errors` | — | — | не перенесено |
| 4 | Голос | VAD (Silero), конец фразы VAD_END_SILENCE / VAD_END_SILENCE_SHORT / VAD_SHORT_UTTER_SEC | hearing.py `SileroVAD`, `_end_silence_for` | — | — | не перенесено |
| 5 | Голос | Окно дослушивания и режим диалога | hearing.py `Hearing` (listen после ответа), agent.py `_idle_after_playback` | — | — | не перенесено |
| 6 | Голос | Закладки («запомни это») | hearing.py `_bookmark_content` | — | — | не перенесено |
| 7 | Голос | Эмоция голоса (анализ и применение) | hearing.py `analyze_voice_emotion`, `apply_voice_emotion` | — | — | не перенесено |
| 8 | Голос | Метки [timeline] (wake → send) | agent.py `send_threadsafe` `_log_timeline` | — | — | не перенесено |
| 9 | Голос | Плеер озвучки: бинарные чанки, счётчик разрывов, PLAYER_PREROLL_MS | voice.py `Player`, `decode_binary_chunk` | — | — | не перенесено |
| 10 | Голос | Выбор устройства вывода (AUDIO_OUTPUT_DEVICE) | voice.py `find_output_device`, `list_output_devices` | — | — | не перенесено |
| 11 | Голос | Перебивание («стоп»), stop_speaking | hearing.py + voice.py `Player.flush` | — | — | не перенесено |
| 12 | Голос | Возврат в idle по tts_end и страховки (stall) | agent.py `_idle_after_playback`, presence.py `Watchdog` | — | — | не перенесено |
| 13 | Сервер | WebSocket к VPS: register, ping/heartbeat, переподключение с backoff | agent.py `run`, `_heartbeat`, `_payload` | — | — | не перенесено |
| 14 | Сервер | Outbox — очередь исходящих при обрыве | outbox.py `Outbox`, `log_send_result` | — | — | не перенесено |
| 15 | Сервер | Обработка command → command_result | agent.py `_recv_loop`, `_run_command` | — | — | не перенесено |
| 16 | Сервер | reply, mood_update, context_transfer | agent.py `_recv_loop` | — | — | не перенесено |
| 17 | Сервер | apps_list после подключения | agent.py `run` → hands.py `scan_apps` | — | — | не перенесено |
| 18 | Сервер | screen_context (анализ экрана) | agent.py `_screen_analysis_loop` | — | — | не перенесено |
| 19 | Сервер | Требование WS_TOKEN (без него не стартует) | config.py, sakura.py | — | — | не перенесено |
| 20 | Расширение | extension_server: порты 8766–8769, проверка Origin и SAKURA_EXTENSION_ID | extension_server.py `_allowed_origins`, `_origin_allowed`, `run_forever` | — | — | не перенесено |
| 21 | Расширение | Все 76 обработчиков background.js (tabs, page_*, youtube_*, bookmarks, history, downloads, zoom…) | extension/background.js | — | — | не перенесено |
| 22 | Расширение | page_content_youtube | extension/background.js | — | — | не перенесено |
| 23 | Расширение | Защита page_fill (пароли, платёжные поля) | extension/background.js | — | — | не перенесено |
| 24 | Присутствие | Heartbeat: CPU, RAM, температуры, GPU, диск | presence.py `get_extended_system_info`, `_collect_system_info`, eyes.py `get_system_info` | — | — | не перенесено |
| 25 | Присутствие | Активное окно и время в нём | eyes.py `get_active_window`, agent.py `_payload` | — | — | не перенесено |
| 26 | Присутствие | Уровень активности (мышь/клавиатура) | presence.py `ActivityWatcher`, `get_activity_level` | — | — | не перенесено |
| 27 | Присутствие | Детектор игр и игровой режим | agent.py `game_mode:*`, settings.py, hearing.py | — | — | не перенесено |
| 28 | Присутствие | orb_arrival/orb_departure с защитой по вводу, OVERLAY_* настройки | agent.py `mood_update`, idle.py, ui/overlay.py `animate_departure` | — | — | не перенесено |
| 29 | Присутствие | Локальное настроение (трек, активность, температура) | local_mood.py `LocalMood` | — | — | не перенесено |
| 30 | Приложения | Сканирование меню «Пуск», Steam, игровых папок (GAME_DIRS) | hands.py `_scan_start_menu`, `_scan_steam`, `_scan_game_dirs`, `scan_apps` | — | — | не перенесено |
| 31 | Приложения | apps_cache.json, запоминание приложения (remember_app) | hands.py `_load_apps_cache`, `_save_apps_cache`, `remember_app` | — | — | не перенесено |
| 32 | Приложения | Индекс файлов и поиск/открытие | file_index.py `FileIndex`, hands.py `find_file`, `open_file` | — | — | не перенесено |
| 33 | Приложения | Локальные голосовые команды (реестр, 36 встроенных + пакеты) | commands.py `CommandRegistry`, hands.py `match_voice_command` | — | — | не перенесено |
| 34 | Приложения | Примитивы hotkey, type_text, focus_window, powershell | hands.py `hotkey`, `type_text`, `focus_window`, `powershell` | — | — | не перенесено |
| 35 | Музыка | SMTC: текущий трек и управление | music.py `_smtc_get_info`, `_smtc_control` | — | — | не перенесено |
| 36 | Музыка | Яндекс.Музыка (приложение): волна, плейлисты, лайки через окно | yamusic_app.py | — | — | не перенесено |
| 37 | Музыка | Лайки/история/плейлисты через API (YANDEX_MUSIC_TOKEN) | music.py `_ym_*` | — | — | не перенесено |
| 38 | Музыка | music_listener — системный звук для эквалайзера | music_listener.py | — | — | не перенесено |
| 39 | Прочее | Скриншоты (JPEG 1280, качество 70) | hands.py `take_screenshot`, `_fit_for_vision` | — | — | не перенесено |
| 40 | Прочее | Чайник по BLE (ключ, статус, нагрев, наблюдение) | kettle.py `KettleClient`, agent.py `_kettle_watch` | — | — | не перенесено |
| 41 | Прочее | Уведомления (show_notification) | ui/overlay.py `show_notification` | — | — | не перенесено |
| 42 | Прочее | exception_hooks | exception_hooks.py `install_exception_hooks` | — | — | не перенесено |
| 43 | Прочее | faulthandler (crash.log) и логи с ротацией (2 МБ × 5) | sakura.py | — | — | не перенесено |
| 44 | Прочее | dep_check — проверка критичных пакетов | dep_check.py `check_critical_packages` | — | — | не перенесено |
| 45 | Прочее | Шина событий, фоновые задачи | events.py `EventBus`, tasks.py `spawn` | — | — | не перенесено |
| 46 | Прочее | Настройки (settings.json) | settings.py `Settings` | — | — | не перенесено |
| 47 | Прочее | Переменные .env (DEVICE_ID, WS_TOKEN, VPS_WS_URL и ещё ~40 из config.py) | config.py | — | — | не перенесено |
| 48 | Прочее | Оверлей PyQt6 (сфера, панель, транскрипт, палитра) | ui/overlay.py | — | — | не перенесено |

## Замечания

- `system.restart`: в старом агенте не работает (в `hands.py` нет ветки `restart`).
  В новом ядре реализуется через `Platform.power("restart")` с тестом.
- Тестов старого агента: 186 (`cd agent; pytest tests -q`). Ядро desktop должно иметь не меньше.
