#!/usr/bin/env python3
"""
agent/tools/test_yamusic.py — диагностика доступа к Яндекс Музыке на ПК.

Запускать на машине Мастера при запущенном десктопном клиенте Яндекс Музыки:
    python agent/tools/test_yamusic.py

Проверяет три канала:
  1.1 SMTC     — сессии через winsdk.windows.media.control
  1.2 Deep links — протокол yandexmusic:// в реестре и os.startfile
  1.3 Hotkeys  — поиск окна и тест ванильных хоткеев
"""
import os
import sys
import time


# ── 1.1 — SMTC ────────────────────────────────────────────────────────
def _check_smtc():
    print("\n=== 1.1 SMTC (GlobalSystemMediaTransportControls) ===")
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Mgr,
        )
    except ImportError:
        print("[FAIL] winsdk не установлен -> pip install winsdk")
        return False
    except Exception as e:
        print(f"[FAIL] winsdk импорт: {e}")
        return False

    try:
        sessions = Mgr.request_async()
    except Exception:
        import asyncio
        sessions = asyncio.get_event_loop().run_until_complete(
            Mgr.request_async().get()
        )

    if sessions is None:
        print("[FAIL] SMTC-менеджер недоступен")
        return False

    try:
        session_list = sessions.get_sessions()
    except TypeError:
        session_list = sessions

    if not session_list:
        print("[WARN] Нет активных медиасессий")
        return False

    yandex_found = False
    print("[OK] Сессии:")
    for s in session_list:
        try:
            aumid = s.source_app_user_model_id
        except Exception:
            aumid = "?"
        title = "?"
        try:
            props = s.try_get_media_properties_async()
            props = props.get() if hasattr(props, "get") else props
            title = getattr(props, "title", "?") or "?"
        except Exception:
            pass
        print(f"  - AUMID={aumid!r}  title={title!r}")
        if "yandex" in (aumid or "").lower() or "yandex" in (title or "").lower():
            yandex_found = True
            try:
                pb = s.get_playback_info()
                print(f"    playback_status: {pb.playback_status}")
                print(f"    is_play_enabled: {getattr(pb,'is_play_enabled',None)}")
            except Exception as e:
                print(f"    playback_info error: {e}")
    if yandex_found:
        print("[OK] Сессия Яндекс Музыки найдена!")
    else:
        print("[WARN] Сессия Яндекс Музыки не найдена среди сессий выше")
    return yandex_found


# ── 1.2 — Deep links ─────────────────────────────────────────────────
def _check_deep_links():
    print("\n=== 1.2 Deep links (yandexmusic://) ===")
    if os.name != "nt":
        print("[SKIP] Только Windows (HKEY_CLASSES_ROOT)")
        return False
    try:
        import winreg
    except ImportError:
        print("[FAIL] winreg unavailable (не Windows)")
        return False

    ym_paths = ["yandexmusic", "YandexMusic", "ymusic"]
    registered = []
    for proto in ym_paths:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, proto) as k:
                val = winreg.QueryValue(k, "")
                registered.append((proto, val))
                print(f"[OK] {proto}:// -> {val!r}")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[ERR] {proto}: {e}")
    if not registered:
        print("[FAIL] Протокол yandexmusic:// НЕ зарегистрирован")
        return False

    try:
        os.startfile("yandexmusic://")
        print("[OK] os.startfile('yandexmusic://') отработал")
        time.sleep(1.0)
    except Exception as e:
        print(f"[ERR] os.startfile: {e}")

    test_links = [
        "yandexmusic://radio/user/onyourwave",
        "yandexmusic://player/message/1",
    ]
    print("Пробные deep links (нужны реальные ID из аккаунта Мастера):")
    for link in test_links:
        try:
            os.startfile(link)
            print(f"  -> {link}: OK")
            time.sleep(0.5)
        except Exception as e:
            print(f"  -> {link}: ERR {e}")
    return bool(registered)


# ── 1.3 — Hotkeys / Window ────────────────────────────────────────────
def _check_hotkeys():
    print("\n=== 1.3 Hotkeys / Window ===")
    try:
        import win32gui
    except ImportError:
        print("[FAIL] pywin32 не установлен -> pip install pywin32")
        return False

    targets = ["Yandex Music", "music"]
    found_hwnd = None
    for title_sub in targets:
        hwnd = win32gui.FindWindow(None, title_sub)
        if not hwnd:
            hwnd = win32gui.FindWindow(None, title_sub.lower())
        if hwnd:
            found_hwnd = hwnd
            print(f"[OK] Окно найдено: {title_sub!r} -> hwnd={hwnd}")
            break

    if not found_hwnd:
        found = []
        def _enum(h, _):
            t = win32gui.GetWindowText(h).lower()
            if any(k in t for k in ("yandex music", "yandex", "music")):
                found.append(h)
        win32gui.EnumWindows(_enum, None)
        if found:
            found_hwnd = found[0]
            print(f"[OK] Окно найдено через EnumWindows: hwnd={found_hwnd}")

    if not found_hwnd:
        print("[WARN] Окно Яндекс Музыки не найдено")
        return False

    print("Рекомендуемые хоткеи для проверки вручную при активном окне:")
    print("  пробел / колесо мыши вверх-вниз — play/pause")
    print("  Ctrl+→ / Ctrl+← — следующий/предыдущий трек")
    print("  L / D — лайк/дизлайк (проверьте в UI)")
    print("  Ctrl+L — фокус поиска, Ctrl+F — поиск по тексту")
    return True


def main():
    print("=" * 60)
    print("Диагностика Яндекс Музыки на ПК")
    print(f"PID={os.getpid()}, time={time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {}
    results["smtc"] = _check_smtc()
    results["deeplinks"] = _check_deep_links()
    results["hotkeys"] = _check_hotkeys()

    print("\n" + "=" * 60)
    print("ИТОГИ:")
    print(f"  SMTC:        {results['smtc']}")
    print(f"  Deep links:  {results['deeplinks']}")
    print(f"  Hotkeys:     {results['hotkeys']}")
    print("=" * 60)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
