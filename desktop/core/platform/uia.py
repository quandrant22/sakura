"""desktop.core.platform.uia — Windows UI Automation через comtypes (без новых зависимостей).

Только чтение и действия с элементами по явной команде; защищённый рабочий стол (UAC)
недоступен — вызовы бросают исключение, выше это превращается в честный отказ.
"""
_uia = None


def client():
    """IUIAutomation (ленивая инициализация: генерация обёртки UIAutomationCore при первом вызове)."""
    global _uia
    if _uia is None:
        import comtypes
        import comtypes.client
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
        _uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
    return _uia


def focused_is_password() -> bool:
    el = client().GetFocusedElement()
    return bool(el and el.CurrentIsPassword)


# ── п. 3.3: действия с элементами активного окна ─────────────────────
_INVOKE, _VALUE, _SCROLL, _SELECTION_ITEM, _TOGGLE = 10000, 10002, 10004, 10010, 10015
_TEXT_TYPES = {50004, 50020, 50030}  # Edit, Text, Document
_SCAN_LIMIT = 3000  # не обходить огромные деревья (браузеры) целиком
READ_LIMIT = 2000


def _gen():
    client()
    from comtypes.gen import UIAutomationClient
    return UIAutomationClient


def _pattern(el, pid, iface):
    unk = el.GetCurrentPattern(pid)
    return unk.QueryInterface(iface) if unk else None


def _root():
    import ctypes
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        raise PermissionError("нет активного окна")
    return client().ElementFromHandle(hwnd)


def _descendants():
    c = client()
    arr = _root().FindAll(4, c.CreateTrueCondition())  # TreeScope_Descendants
    for i in range(min(arr.Length, _SCAN_LIMIT)):
        yield arr.GetElement(i)


def find(name: str):
    """Элемент активного окна по имени: сначала точное совпадение, затем по вхождению."""
    want = name.strip().lower()
    partial = None
    for el in _descendants():
        n = (el.CurrentName or "").strip().lower()
        if not n or el.CurrentIsOffscreen:
            continue
        if n == want:
            return el
        if partial is None and want in n:
            partial = el
    return partial


def click(name: str) -> bool | None:
    """None — элемент не найден."""
    el = find(name)
    if el is None:
        return None
    g = _gen()
    for pid, iface, call in ((_INVOKE, g.IUIAutomationInvokePattern, "Invoke"),
                             (_TOGGLE, g.IUIAutomationTogglePattern, "Toggle"),
                             (_SELECTION_ITEM, g.IUIAutomationSelectionItemPattern, "Select")):
        pat = _pattern(el, pid, iface)
        if pat:
            getattr(pat, call)()
            return True
    r = el.CurrentBoundingRectangle
    if r.right <= r.left or r.bottom <= r.top:
        return False
    import pyautogui
    pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    return True


def type_into(name: str, text: str) -> str:
    """'done' | 'not_found' | 'password' | 'readonly'."""
    el = find(name) if name else client().GetFocusedElement()
    if el is None:
        return "not_found"
    if el.CurrentIsPassword:
        return "password"
    pat = _pattern(el, _VALUE, _gen().IUIAutomationValuePattern)
    if pat:
        if pat.CurrentIsReadOnly:
            return "readonly"
        pat.SetValue(text)
        return "done"
    el.SetFocus()
    import pyautogui
    pyautogui.write(text, interval=0.01)
    return "done"


def scroll(direction: str, pages: int = 1) -> bool:
    """Прокрутка первого прокручиваемого элемента; иначе колесом мыши."""
    vert = {"down": 1, "up": 0}  # ScrollAmount_LargeIncrement / LargeDecrement
    horiz = {"right": 1, "left": 0}
    g = _gen()
    for el in _descendants():
        pat = _pattern(el, _SCROLL, g.IUIAutomationScrollPattern)
        if pat and (pat.CurrentVerticallyScrollable if direction in vert else pat.CurrentHorizontallyScrollable):
            for _ in range(pages):
                if direction in vert:
                    pat.Scroll(2, vert[direction])  # 2 — NoAmount по горизонтали
                else:
                    pat.Scroll(horiz[direction], 2)
            return True
    if direction not in vert:
        return False
    import pyautogui
    pyautogui.scroll((-5 if direction == "down" else 5) * 100 * pages)
    return True


def _field_text(el) -> str:
    """Текст поля редактирования (Edit/Document): в Name у них подпись («Текстовый редактор»),
    а содержимое — в ValuePattern или TextPattern (живая проверка 14.10, Блокнот)."""
    g = _gen()
    try:
        pat = _pattern(el, _VALUE, g.IUIAutomationValuePattern)
        if pat and pat.CurrentValue:
            return pat.CurrentValue.strip()
        unk = el.GetCurrentPattern(10014)  # TextPattern
        if unk:
            tp = unk.QueryInterface(g.IUIAutomationTextPattern)
            return (tp.DocumentRange.GetText(READ_LIMIT) or "").strip()
    except Exception:  # noqa: BLE001
        return ""
    return ""


def read(name: str = "") -> str:
    """Видимый текст активного окна (или одного элемента), без полей паролей."""
    if name:
        el = find(name)
        if el is None or el.CurrentIsPassword:
            return ""
        pat = _pattern(el, _VALUE, _gen().IUIAutomationValuePattern)
        return ((pat.CurrentValue if pat else "") or el.CurrentName or "")[:READ_LIMIT]
    out, size, seen = [], 0, set()
    for el in _descendants():
        if el.CurrentControlType not in _TEXT_TYPES or el.CurrentIsPassword or el.CurrentIsOffscreen:
            continue
        field = _field_text(el) if el.CurrentControlType in (50004, 50030) else ""
        t = field or (el.CurrentName or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
            size += len(t)
            if size >= READ_LIMIT:
                break
    return "\n".join(out)[:READ_LIMIT]


def window_by_title(prefix: str):
    """Элемент видимого окна верхнего уровня, чей заголовок начинается с prefix (или None)."""
    import ctypes
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(h, buf, 512)
        if buf.value.startswith(prefix) and ctypes.windll.user32.IsWindowVisible(h):
            found.append(h)
            return False
        return True
    ctypes.windll.user32.EnumWindows(cb, 0)
    return client().ElementFromHandle(found[0]) if found else None
