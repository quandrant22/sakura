"""
ws_handler_secure.py — безопасная замена ws_handler из main.py.

Вставить вместо оригинальной функции ws_handler в main.py.
Добавить в импорты: from modules.ws_auth import check_token, is_master_device, reject

Изменения относительно оригинала:
  1. Каждое входящее сообщение проверяется через check_token().
  2. Деструктивные типы (voice_command с wipe, apps_list) — только от master-устройств.
  3. Явный reject() с логом при несовпадении токена.
  4. register/ping больше не принимаются без токена.
"""

# ─────────────────────────────────────────────
#  Вставить в начало main.py после существующих импортов:
#
#  from modules.ws_auth import check_token, is_master_device, reject, validate_secret_on_startup
#
# ─────────────────────────────────────────────


async def ws_handler(websocket):
    device_id = None
    try:
        async for raw in websocket:
            try:
                data     = json.loads(raw)
                msg_type = data.get("type")

                # ── Аутентификация — первое, до любой обработки ────────────
                if not check_token(data):
                    await reject(websocket, reason=f"invalid token on '{msg_type}'")
                    return

                # ── Деструктивные операции — только master-устройства ───────
                # voice_command может содержать «протокол чистый лист»;
                # apps_list перезаписывает маппинг приложений.
                dev_from_msg = data.get("device_id")
                if msg_type in ("voice_command", "apps_list"):
                    if not is_master_device(dev_from_msg):
                        await reject(
                            websocket,
                            reason=f"'{msg_type}' denied: not a master device ({dev_from_msg!r})"
                        )
                        return

                # ── Стандартная обработка (без изменений из оригинала) ──────

                if msg_type == "register":
                    device_id = data.get("device_id")
                    connected_devices[device_id] = websocket
                    update_device(device_id,
                        active_window = data.get("active_window"),
                        context       = data.get("context"),
                        system_info   = data.get("system_info"))
                    log.info(f"Устройство подключено: {device_id}")

                elif msg_type == "ping":
                    device_id = data.get("device_id")
                    connected_devices[device_id] = websocket
                    update_device(device_id,
                        active_window = data.get("active_window"),
                        context       = data.get("context"),
                        system_info   = data.get("system_info"))

                elif msg_type == "apps_list":
                    device_id = data.get("device_id")
                    apps      = data.get("apps", {})\
                    
                    log.info(f"Приложения от {device_id}: {len(apps)}")
                    asyncio.create_task(analyze_apps(apps, device_id))

                elif msg_type == "command_result":
                    result     = data.get("result")
                    screenshot = data.get("screenshot")
                    dev_name   = data.get("device_id", "устройство")
                    if screenshot:
                        img_data = base64.b64decode(screenshot)
                        await bot.send_photo(MASTER_ID,
                            photo   = BufferedInputFile(img_data, "screenshot.jpg"),
                            caption = f"Скриншот с {dev_name}, Мастер.")
                    elif result and result.startswith("app_not_found:"):
                        app_name = result.split(":", 1)[1]
                        reply    = await ask_gemini(
                            f"Приложение '{app_name}' не найдено на {dev_name}. "
                            f"Скажи коротко и предложи написать путь: "
                            f"'запомни {app_name} = C:\\\\путь\\\\к\\\\файлу.exe'",
                            save_history=False)
                        await bot.send_message(MASTER_ID, reply)
                    elif result:
                        err_triggers = ("ошибка", "не нашла", "не найдено", "app_not_found", "оффлайн")
                        if any(t in result.lower() for t in err_triggers):
                            await bot.send_message(MASTER_ID, result)

                elif msg_type == "tg_message":
                    await bot.send_message(MASTER_ID, f"📝 {data.get('text','')}")

                elif msg_type == "voice_command":
                    device_id  = data.get("device_id")
                    text       = data.get("text", "")
                    context    = data.get("context", [])
                    ctx_str    = f"\n\nПассивный контекст: {' | '.join(context)}" if context else ""
                    ws_dev     = connected_devices.get(device_id)
                    text_lower = text.lower()

                    if "протокол чистый лист" in text_lower:
                        # ── Деструктивно: wipe памяти — только если дошло сюда
                        # (проверка is_master_device уже выполнена выше)
                        await _clean_slate()
                        if ws_dev:
                            phrase = "Протокол выполнен. Я тебя не помню."
                            await ws_dev.send(json.dumps({
                                "type": "reply", "device_id": device_id or "laptop", "text": phrase,
                            }))
                        continue

                    # ── написать VIP по голосу ──
                    _vip = _find_vip_by_name(text)
                    log.info(f"voice->vip check: text={text!r} vip={_vip}")
                    if _vip and any(v in text_lower for v in
                                    ("напиши", "напишите", "передай", "сообщи", "скажи")):
                        vip_id, vip_name = _vip

                        async def _sayv(phrase):
                            if ws_dev:
                                await stream_tts_to_device(phrase, ws_dev, device_id or "laptop", literal=True)

                        if "чтобы" in text_lower:
                            msg = text_lower.split("чтобы", 1)[1]
                        elif "что" in text_lower:
                            msg = text_lower.split("что", 1)[1]
                        else:
                            msg = text_lower
                            for w in ("напиши", "напишите", "передай", "сообщи", "скажи", "сакура", vip_name):
                                msg = msg.replace(w, " ")
                        msg = " ".join(msg.split()).strip(" ,.")
                        log.info(f"voice->vip msg={msg!r} -> {vip_name}({vip_id})")

                        if not msg:
                            await _sayv(f"Что передать {vip_name.capitalize()}?")
                            continue
                        try:
                            await bot.send_message(int(vip_id), msg)
                            log.info("voice->vip SENT OK")
                            await _sayv(f"Передала {vip_name.capitalize()}.")
                        except Exception as e:
                            log.error(f"voice->vip SEND FAIL: {e}")
                            await _sayv("Не получилось отправить, Мастер.")
                        continue

                    # ── отправка в Telegram по голосу ──
                    _SEND = ("пришли", "отправь", "скинь", "кинь", "сбрось", "напиши")
                    _TG = ("в тг", "в телеграм", "в телегу", "в телеге", "в личк", "сообщением", "мне в чат")
                    if any(v in text_lower for v in _SEND) and any(t in text_lower for t in _TG):
                        payload = text_lower
                        for w in _SEND + _TG + ("мне", "пожалуйста", "сакура"):
                            payload = payload.replace(w, " ")
                        payload = " ".join(payload.split()).strip(" ,.")

                        async def _say(phrase):
                            if ws_dev:
                                await stream_tts_to_device(phrase, ws_dev, device_id or "laptop", literal=True)

                        if not payload:
                            await _say("Что прислать в телеграм, Мастер?")
                            continue

                        aw = data.get("active_window", "")
                        use_ctx = any(w in payload for w in
                                      ("это", "этого", "на экране", "что вижу", "тут", "здесь", "по этому"))
                        query = f"{payload} {aw}".strip() if (use_ctx and aw) else payload

                        gen    = any(w in payload for w in ("нарисуй", "сгенерируй", "сгенери", "придумай", "сделай арт"))
                        is_img = (len(payload.split()) <= 8 and any(w in payload for w in
                                  ("картинк", "фото", "изображени", "рисунок", "арт", "мем", "пикч", "нарисуй")))
                        try:
                            if is_img and gen:
                                desc = query
                                for w in ("нарисуй", "сгенерируй", "сгенери", "придумай", "картинку",
                                          "картинка", "фото", "изображение", "арт", "мем", "пикчу"):
                                    desc = desc.replace(w, " ")
                                img = await generate_image_by_prompt(" ".join(desc.split()).strip() or "аниме сакура")
                                if img:
                                    await bot.send_photo(MASTER_ID,
                                        photo=BufferedInputFile(img, "image.jpg"), caption=query)
                                    await _say("Нарисовала и отправила, Мастер.")
                                else:
                                    await _say("Не получилось нарисовать, Мастер.")
                            elif is_img:
                                q = query
                                for w in ("найди", "поищи", "покажи", "картинку", "картинка", "картинки",
                                          "фото", "фотку", "фотографию", "изображение", "рисунок", "арт", "мем", "пикчу"):
                                    q = q.replace(w, " ")
                                q = " ".join(q.split()).strip()
                                q_en = await _translate_en(q)
                                urls = await search_image(q_en, count=1)
                                img = await download_bytes(urls[0]) if urls else None
                                if img:
                                    await bot.send_photo(MASTER_ID,
                                        photo=BufferedInputFile(img, "image.jpg"), caption=q)
                                    await _say("Нашла картинку и отправила, Мастер.")
                                elif urls:
                                    await bot.send_message(MASTER_ID, urls[0])
                                    await _say("Отправила ссылкой, Мастер.")
                                else:
                                    await _say("Не нашла картинку, Мастер.")
                            elif needs_search(payload):
                                res = await search_and_fetch(query)
                                await send_safe(MASTER_ID, res or "По запросу ничего не нашла.")
                                await _say("Нашла в интернете и отправила, Мастер.")
                            else:
                                answer = await ask_gemini(payload, save_history=False)
                                await send_safe(MASTER_ID, answer)
                                await _say("Отправила в телеграм, Мастер.")
                        except Exception as e:
                            log.error(f"voice->tg: {e}")
                            await _say("Не получилось, Мастер.")
                        continue

                    if ws_dev:
                        chosen = {"dev": device_id or "laptop"}
                        def _resolve(q):
                            d, t = resolve_app(q, device_id)
                            if t:
                                chosen["dev"] = d
                            return t
                        actions = device_commands.parse(text, _resolve)
                        for action, _label in actions:
                            dev = chosen["dev"]
                            tws = connected_devices.get(dev, ws_dev)
                            if action.startswith("say:"):
                                await stream_tts_to_device(action[4:], tws, dev, literal=True)
                            else:
                                await tws.send(json.dumps({"type": "command", "action": action}))
                            await asyncio.sleep(0.3)
                        if actions:
                            continue

                    active_win = data.get("active_window", "")
                    await ask_gemini_voice(
                        user_message  = text + ctx_str,
                        websocket     = ws_dev,
                        device_id     = device_id or "laptop",
                        active_window = active_win,
                    )

            except Exception as e:
                log.error(f"[ws_handler] {e}")

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if device_id:
            set_device_offline(device_id)
            connected_devices.pop(device_id, None)
            log.info(f"Устройство отключено: {device_id}")
