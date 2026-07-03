"""
Тест browser.py — запускай на ноуте где стоит агент.
Opera GX должна быть открыта.

python test_browser.py
"""
import sys, time
sys.path.insert(0, r"C:\Sakura")  # путь к агенту

from core.browser import (
    _find_opera_hwnd, _focus_opera,
    browser_tab_new, browser_tab_close, browser_tab_next,
    browser_scroll_down, browser_back, browser_forward,
    browser_open_url, browser_search,
    music_play_pause, music_next, music_track, music_open,
)

def test(name, fn, *args):
    print(f"\n[{name}]", end=" ")
    try:
        result = fn(*args) if args else fn()
        print(f"✓ {result}")
    except Exception as e:
        print(f"✗ {e}")
    time.sleep(1.5)

print("=== Проверяем Opera GX ===")
hwnd = _find_opera_hwnd()
print(f"Opera hwnd: {hwnd}")
if not hwnd:
    print("Opera GX не найдена! Открой браузер и запусти снова.")
    sys.exit(1)

print("\nОткрываю Яндекс Музыку...")
test("music:open", music_open)
time.sleep(2)

print("\n=== Браузер ===")
test("новая вкладка", browser_tab_new)
time.sleep(0.5)
test("открыть URL", browser_open_url, "https://music.yandex.ru")
time.sleep(1.5)
test("прокрутить вниз", browser_scroll_down)
test("назад", browser_back)
test("вперёд", browser_forward)
test("закрыть вкладку", browser_tab_close)

print("\n=== Яндекс Музыка ===")
test("найти трек", music_track, "Miyagi Эндшпиль")
time.sleep(2)
test("пауза", music_play_pause)
time.sleep(0.5)
test("следующий", music_next)

print("\n=== Готово ===")
