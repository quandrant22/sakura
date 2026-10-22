"""Реестр действий управления ПК: канонический id → обработчик и флаги (reversible, confirm)."""
import os
from collections.abc import Callable
from dataclasses import dataclass, field

from desktop.core import results as R
from desktop.core.control import safety


@dataclass
class Ctx:
    """Зависимости обработчиков — подменяются в тестах (подставной платформенный слой)."""
    platform: object = None
    keyboard: object = None     # press(key) / hotkey(*keys) / write(text) — pyautogui
    clipboard: object = None    # copy(text) / paste() — pyperclip
    processes: Callable | None = None   # () → [{'pid', 'name', 'memory_mb'}]
    kill: Callable | None = None        # (pid) → bool
    files: object = None        # hands: open_file(name) / find_file(name) / recent()
    fs: object = None           # copy(src, dst) / move(src, dst)
    ui: object = None           # UI Automation: click / type_into / scroll / read (platform.uia)
    apps: object = None         # AppLauncher (подменяется в тестах)
    extra: dict = field(default_factory=dict)

    @classmethod
    def default(cls) -> "Ctx":
        from desktop.core.platform import get_platform
        return cls(platform=get_platform(), keyboard=_Keyboard(), clipboard=_Clipboard(),
                   processes=_process_list, kill=_process_kill, files=_Files(), fs=_Fs(),
                   ui=_ui_module())


@dataclass
class Action:
    fn: Callable[[str, Ctx], dict]
    reversible: bool
    confirm: bool
    # ui.* и keys.* — не в окна из чёрного списка
    guard_window: bool = False


# ── реальные реализации (тонкие обёртки над библиотеками) ─────────────
def _ui_module():
    if os.name != "nt":
        return None
    from desktop.core.platform import uia
    return uia


class _Keyboard:
    def __getattr__(self, name):
        import pyautogui
        return getattr(pyautogui, name)


class _Clipboard:
    def copy(self, text: str):
        import pyperclip
        pyperclip.copy(text)

    def paste(self) -> str:
        import pyperclip
        return pyperclip.paste()


def _process_list() -> list[dict]:
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        mem = p.info.get("memory_info")
        out.append({"pid": p.info["pid"], "name": p.info.get("name") or "",
                    "memory_mb": round(mem.rss / 2**20) if mem else 0})
    return out


def _process_kill(pid: int) -> bool:
    import psutil
    p = psutil.Process(pid)
    p.terminate()
    try:
        p.wait(timeout=3)
    except psutil.TimeoutExpired:
        return False
    return True


class _Files:
    def open_file(self, name: str) -> str:
        from desktop.core import hands
        return hands.open_file(name)

    def find(self, name: str) -> str | None:
        from desktop.core import hands
        if os.path.exists(name):
            return name
        found = hands.find_file(name, limit=1)
        return found[0] if found else None

    def recent(self, limit: int = 10) -> list[str]:
        folder = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Recent")
        try:
            items = sorted((e for e in os.scandir(folder) if e.name.endswith(".lnk")),
                           key=lambda e: e.stat().st_mtime, reverse=True)
        except OSError:
            return []
        return [os.path.splitext(e.name)[0] for e in items[:limit]]


class _Fs:
    def copy(self, src: str, dst: str) -> str:
        import shutil
        return shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy2(src, dst)

    def move(self, src: str, dst: str) -> str:
        import shutil
        return shutil.move(src, dst)


# ── обработчики ──────────────────────────────────────────────────────
def _target_window(arg: str, ctx: Ctx) -> dict | None:
    """Окно по части заголовка или имени процесса; без аргумента — активное."""
    q = (arg or "").strip().lower()
    if not q:
        return ctx.platform.foreground_window()
    for w in ctx.platform.windows():
        if q in w["title"].lower() or q in (w.get("process") or "").lower():
            return w
    return None


def _window_state(state: str):
    def run(arg: str, ctx: Ctx) -> dict:
        w = _target_window(arg, ctx)
        if not w:
            return R.failed("окно не найдено")
        ok = ctx.platform.window_show(w["hwnd"], state)
        label = {"minimize": "свернула", "maximize": "развернула", "restore": "восстановила"}[state]
        return R.done(f"{label} «{w['title']}»") if ok else R.failed("не удалось")
    return run


def window_snap(arg: str, ctx: Ctx) -> dict:
    side, _, title = (arg or "").partition(":")
    side = {"лево": "left", "влево": "left", "право": "right", "вправо": "right", "вверх": "top"}.get(side, side)
    if side not in ("left", "right", "top"):
        return R.failed("сторона: left, right или top")
    w = _target_window(title, ctx)
    if not w:
        return R.failed("окно не найдено")
    if ctx.platform.window_snap(w["hwnd"], side):
        return R.done(f"окно «{w['title']}» — {side}")
    return R.failed("не удалось")


def window_move_monitor(arg: str, ctx: Ctx) -> dict:
    target, _, title = (arg or "next").partition(":")
    w = _target_window(title, ctx)
    if not w:
        return R.failed("окно не найдено")
    if ctx.platform.window_to_monitor(w["hwnd"], target or "next"):
        return R.done(f"перенесла «{w['title']}» на другой монитор")
    return R.unsupported("второго монитора нет или номер неверный")


def window_focus(arg: str, ctx: Ctx) -> dict:
    if not (arg or "").strip():
        return R.failed("не указано окно")
    w = _target_window(arg, ctx)
    if not w:
        return R.failed(f"окно «{arg}» не найдено")
    return R.done(f"переключилась на «{w['title']}»") if ctx.platform.activate_window_handle(w["hwnd"]) \
        else R.failed("окно не вышло вперёд")


def window_list(arg: str, ctx: Ctx) -> dict:
    titles = [w["title"] for w in ctx.platform.windows()][:30]
    # Ответ — данные для пересказа моделью; в журнал попадает только факт.
    return R.done("Открытые окна: " + "; ".join(titles) if titles else "Открытых окон нет", windows=titles)


def power_lock(arg, ctx):
    ctx.platform.power("lock")
    return R.done("заблокировано")


def power_sleep(arg, ctx):
    ctx.platform.power("sleep")
    return R.done("уходим в сон")


def power_display_off(arg, ctx):
    ctx.platform.display_off()
    return R.done("экран погашен")


def process_list(arg: str, ctx: Ctx) -> dict:
    top = sorted(ctx.processes(), key=lambda p: -p["memory_mb"])[:15]
    text = "; ".join(f"{p['name']} ({p['memory_mb']} МБ)" for p in top)
    return R.done(f"Больше всего памяти: {text}", processes=top)


def process_kill(arg: str, ctx: Ctx) -> dict:
    q = (arg or "").strip().lower()
    if not q:
        return R.failed("не указан процесс")
    found = [p for p in ctx.processes() if str(p["pid"]) == q or p["name"].lower() in (q, f"{q}.exe")]
    if not found:
        return R.failed(f"процесс «{arg}» не найден")
    if any(p["name"].lower() in safety.PROTECTED_PROCESSES for p in found):
        return R.unsupported("системный процесс или сама Сакура — не завершаю")
    done = [p for p in found if ctx.kill(p["pid"])]
    return R.done(f"завершила {found[0]['name']}") if done else R.failed("процесс не завершился")


def clipboard_read(arg, ctx):
    text = ctx.clipboard.paste() or ""
    return R.done(text[:2000] if text else "буфер обмена пуст")


def clipboard_write(arg, ctx):
    ctx.clipboard.copy(arg or "")
    return R.done("скопировала в буфер обмена")


def clipboard_clear(arg, ctx):
    ctx.clipboard.copy("")
    return R.done("буфер обмена очищен")


def display_brightness(arg, ctx):
    if not (arg or "").strip().isdigit():
        return R.failed("уровень яркости 0–100")
    level = max(0, min(100, int(arg)))
    if ctx.platform.set_brightness(level):
        return R.done(f"яркость {level}%")
    return R.unsupported("этот монитор не даёт менять яркость программно")


def display_night_light(arg, ctx):
    # У Windows нет публичного API ночного режима; правка недокументированного реестра — нет.
    opener = ctx.platform.open_path
    opener("ms-settings:nightlight")
    return R.unsupported("ночной режим включается в настройках Windows — открыла их")


def audio_mic_mute(arg, ctx):
    want = {"on": True, "вкл": True, "off": False, "выкл": False}.get((arg or "").strip().lower())
    muted = ctx.platform.mic_mute(want)
    if muted is None:
        return R.unsupported("микрофон не найден")
    return R.done("микрофон выключен" if muted else "микрофон включён")


def _radio(kind: str):
    def run(arg, ctx):
        on = {"on": True, "вкл": True, "off": False, "выкл": False}.get((arg or "").strip().lower())
        if on is None:
            return R.failed("on или off")
        name = "Wi-Fi" if kind == "wifi" else "Bluetooth"
        if ctx.platform.radio(kind, on):
            return R.done(f"{name} {'включён' if on else 'выключен'}")
        return R.unsupported(f"{name}: адаптер не найден или доступ запрещён")
    return run


def _guard_active(ctx: Ctx) -> dict | None:
    w = ctx.platform.foreground_window() or {}
    if safety.blocked_window(w.get("title", ""), w.get("process", "")):
        return R.unsupported("это окно в чёрном списке — ввод запрещён")
    return None


def keys_type(arg, ctx):
    if not arg:
        return R.failed("нечего вводить")
    if ctx.platform.focused_is_password():
        return R.unsupported("поле пароля — не ввожу")
    ctx.keyboard.write(arg, interval=0.01)
    return R.done("ввела текст")  # сам текст в ответ и журнал не попадает


def keys_hotkey(arg, ctx):
    combo = safety.normalize_hotkey(arg or "")
    if not combo:
        return R.unsupported("сочетание не из разрешённых")
    ctx.keyboard.hotkey(*combo.split("+"))
    return R.done(f"нажала {combo}")


def keys_media(arg, ctx):
    kind = (arg or "").strip().lower()
    if kind not in ("play_pause", "next", "prev", "mute", "volume_up", "volume_down"):
        return R.failed("медиаклавиша: play_pause, next, prev, mute, volume_up, volume_down")
    ctx.platform.media_key(kind)
    return R.done(f"медиаклавиша {kind}")


def files_open(arg, ctx):
    return R.from_legacy(ctx.files.open_file(arg or ""))


def _env(ctx):
    return ctx.extra.get("env") or os.environ


def _checked(ctx, path, **kw) -> str:
    from desktop.core.control import files_safe as F
    return F.check_path(path, env=_env(ctx), **kw)


def _refused(e) -> dict:
    return R.unsupported(str(e))


def files_find(arg, ctx):
    """Поиск по имени (только чтение): «имя» или «имя|папка»; до 3 кандидатов с полным путём."""
    from desktop.core.control import files_safe as F
    name, _, folder = (arg or "").partition("|")
    try:
        found = F.find(name, folder.strip() or None, env=_env(ctx))
    except F.PathRefused as e:
        return _refused(e)
    if not found:
        return R.failed("файл не найден в Загрузках, Документах, на Рабочем столе, в Изображениях, Видео и Музыке")
    lines = "; ".join(f"{c['path']} ({c['size']} байт)" for c in found)
    return R.done(f"Нашла: {lines}", files=found)


def files_reveal(arg, ctx):
    from desktop.core.control import files_safe as F
    try:
        path = _checked(ctx, arg, allow_exec=True)
    except F.PathRefused as e:
        return _refused(e)
    return R.done("показала файл в проводнике") if ctx.platform.reveal(path) else R.failed("не удалось")


def files_recent(arg, ctx):
    items = ctx.files.recent()
    return R.done("Недавние: " + "; ".join(items) if items else "недавних файлов нет", files=items)


def _two_paths(arg: str) -> tuple[str, str] | None:
    src, sep, dst = (arg or "").partition("|")
    return (src.strip(), dst.strip()) if sep and src.strip() and dst.strip() else None


def _dest(ctx, dst: str, src: str) -> str:
    """Куда копировать/переносить: полный путь (папка — тогда то же имя); существующий файл не перезаписывается."""
    from desktop.core.control import files_safe as F
    raw = (dst or "").strip().strip('"')
    if os.path.isdir(raw):
        raw = os.path.join(raw, os.path.basename(src))
    full = F.check_path(raw, env=_env(ctx), must_exist=False)
    if os.path.exists(full):
        raise F.PathRefused("по этому пути уже есть файл — не перезаписываю")
    if not os.path.isdir(os.path.dirname(full)):
        raise F.PathRefused("папки назначения нет")
    return full


def files_copy(arg, ctx):
    from desktop.core.control import files_safe as F
    pair = _two_paths(arg)
    if not pair:
        return R.failed("нужно «полный путь откуда|куда»")
    try:
        src = _checked(ctx, pair[0])
        dst = _dest(ctx, pair[1], src)
    except F.PathRefused as e:
        return _refused(e)
    ctx.fs.copy(src, dst)
    return R.done(f"скопировала в {dst}")


def files_move(arg, ctx):
    from desktop.core.control import files_safe as F
    pair = _two_paths(arg)
    if not pair:
        return R.failed("нужно «полный путь откуда|куда»")
    try:
        src = _checked(ctx, pair[0])
        dst = _dest(ctx, pair[1], src)
    except F.PathRefused as e:
        return _refused(e)
    ctx.fs.move(src, dst)
    return R.done(f"переместила в {dst}")


def files_delete_preview(arg, ctx):
    """Что будет удалено — без выполнения."""
    from desktop.core.control import files_safe as F
    try:
        path = _checked(ctx, arg)
    except F.PathRefused as e:
        return _refused(e)
    size = os.path.getsize(path)
    return R.done(f"Будет удалено в корзину: {path} ({size} байт)", path=path, size=size)


def files_delete(arg, ctx):
    from desktop.core.control import files_safe as F
    try:
        path = _checked(ctx, arg)
    except F.PathRefused as e:
        return _refused(e)
    if not ctx.platform.recycle(path):
        return R.failed("не удалось удалить в корзину")
    journal = ctx.extra.get("journal") or F.default_journal()
    journal.add(path)
    return R.done(f"удалила в корзину: {path}")


def files_undelete(arg, ctx):
    """Вернуть удалённое Сакурой: последние 5 за 24 часа (или одно — по полному пути)."""
    from desktop.core.control import files_safe as F
    journal = ctx.extra.get("journal") or F.default_journal()
    items = journal.recent()
    want = (arg or "").strip().strip('"')
    if want:
        items = [e for e in items if os.path.normcase(e["path"]) == os.path.normcase(want)]
    if not items:
        return R.noop("этого файла нет в журнале удалений" if want else "за последние сутки Сакура ничего не удаляла")
    restored, failed = [], []
    for e in reversed(items if not want else items[-1:]):
        if os.path.exists(e["path"]):
            failed.append(e["path"])
            continue
        if ctx.platform.restore_from_recycle(e["path"]):
            journal.mark_restored(e["path"])
            restored.append(e["path"])
        else:
            failed.append(e["path"])
        if not want:
            break  # «верни удалённый файл» — последний; список — через files.undelete с путём
    if restored:
        return R.done(f"вернула: {'; '.join(restored)}", files=restored)
    return R.failed("не удалось вернуть из корзины — возможно, корзину очистили")


# ── UI Automation (п. 3.3): только активное окно, не в чёрном списке ──
def _need_ui(ctx):
    if ctx.ui is None:
        raise NotImplementedError


def ui_click(arg, ctx):
    _need_ui(ctx)
    name = (arg or "").strip()
    if not name:
        return R.failed("какой элемент нажать?")
    res = ctx.ui.click(name)
    if res is None:
        return R.failed(f"не нашла «{name}» в активном окне")
    return R.done(f"нажала «{name}»") if res else R.failed("элемент не нажимается")


def ui_type(arg, ctx):
    _need_ui(ctx)
    name, sep, text = (arg or "").partition("|")
    if not sep:
        name, text = "", arg or ""
    if not text:
        return R.failed("нечего вводить")
    res = ctx.ui.type_into(name.strip(), text)
    return {"done": R.done("ввела текст"),
            "not_found": R.failed(f"не нашла поле «{name.strip()}»"),
            "password": R.unsupported("поле пароля — не ввожу"),
            "readonly": R.failed("поле только для чтения")}.get(res, R.failed("не удалось ввести"))


def ui_scroll(arg, ctx):
    _need_ui(ctx)
    direction, _, n = (arg or "down").strip().lower().partition(":")
    direction = {"вниз": "down", "вверх": "up", "влево": "left", "вправо": "right"}.get(direction, direction)
    if direction not in ("down", "up", "left", "right"):
        return R.failed("направление: down, up, left, right")
    pages = max(1, min(int(n), 10)) if n.isdigit() else 1
    return R.done("прокрутила") if ctx.ui.scroll(direction, pages) else R.failed("нечего прокручивать")


def ui_read(arg, ctx):
    _need_ui(ctx)
    text = ctx.ui.read((arg or "").strip())
    return R.done(text, text=text) if text else R.failed("текста не нашла")


# ── приложения (шаг Е): перезапуск с параметрами из белого списка ──
def app_restart(arg, ctx):
    from desktop.core import app_launch
    key = app_launch.app_key(arg or "яндекс музыка")
    if key is None:
        return R.unsupported("перезапускать можно только Яндекс.Музыку")
    return (ctx.apps or app_launch.AppLauncher()).restart(key)


ACTIONS: dict[str, Action] = {
    "window.minimize": Action(_window_state("minimize"), True, False),
    "window.maximize": Action(_window_state("maximize"), True, False),
    "window.restore": Action(_window_state("restore"), True, False),
    "window.snap": Action(window_snap, True, False),
    "window.move_monitor": Action(window_move_monitor, True, False),
    "window.focus": Action(window_focus, True, False),
    "window.list": Action(window_list, True, False),
    "power.lock": Action(power_lock, True, False),
    "power.sleep": Action(power_sleep, False, True),
    "power.display_off": Action(power_display_off, True, False),
    "process.list": Action(process_list, True, False),
    "process.kill": Action(process_kill, False, True),
    "clipboard.read": Action(clipboard_read, True, False),
    "clipboard.write": Action(clipboard_write, False, False),
    "clipboard.clear": Action(clipboard_clear, False, False),
    "display.brightness": Action(display_brightness, True, False),
    "display.night_light": Action(display_night_light, True, False),
    "audio.mic_mute": Action(audio_mic_mute, True, False),
    "net.wifi": Action(_radio("wifi"), True, True),
    "net.bluetooth": Action(_radio("bluetooth"), True, False),
    "keys.type": Action(keys_type, False, False, guard_window=True),
    "keys.hotkey": Action(keys_hotkey, False, False, guard_window=True),
    "keys.media": Action(keys_media, True, False),
    "ui.click": Action(ui_click, False, False, guard_window=True),
    "ui.type": Action(ui_type, False, False, guard_window=True),
    "ui.scroll": Action(ui_scroll, True, False, guard_window=True),
    "ui.read": Action(ui_read, True, False, guard_window=True),
    "app.restart": Action(app_restart, True, False),
    "files.open": Action(files_open, True, False),
    "files.reveal": Action(files_reveal, True, False),
    "files.recent": Action(files_recent, True, False),
    "files.find": Action(files_find, True, False),
    "files.copy": Action(files_copy, True, False),
    "files.move": Action(files_move, False, True),
    "files.delete_preview": Action(files_delete_preview, True, False),
    "files.delete": Action(files_delete, True, True),
    "files.undelete": Action(files_undelete, True, False),
}

_limiter = safety.RateLimiter()


def execute(action: str, arg: str = "", confirmed: bool = False, ctx: Ctx | None = None,
            limiter: safety.RateLimiter | None = None) -> dict:
    """Выполнить действие управления ПК с проверками безопасности; журнал — id и статус."""
    a = ACTIONS.get(action)
    if a is None:
        return R.unsupported(f"неизвестное действие: {action}")
    if safety.PAUSED["on"]:
        res = R.unsupported("управление компьютером остановлено аварийной кнопкой — нажми «Возобновить»")
    elif a.confirm and not confirmed:
        res = R.unsupported("нужно подтверждение")
    elif not (limiter or _limiter).allow():
        res = R.failed("слишком много действий подряд — не больше 5 в секунду")
    else:
        ctx = ctx or Ctx.default()
        guard = _guard_active(ctx) if a.guard_window else None
        if guard:
            res = guard
        else:
            try:
                res = a.fn(arg, ctx)
            except NotImplementedError:
                res = R.unsupported("недоступно на этой системе")
            except PermissionError:
                res = R.unsupported("нет прав (защищённый рабочий стол или окно администратора)")
            except Exception as e:  # noqa: BLE001
                res = R.failed(f"ошибка: {type(e).__name__}")
    safety.journal(action, res["status"])
    return res
