"""desktop.core.media.ym_ui — кнопки окна Яндекс.Музыки через UI Automation (запасной путь).

Приложение (Electron) не отдаёт перемешивание и повтор в SMTC. Кнопки видны в UI Automation,
только если в приложении включена доступность Chromium (запуск с --force-renderer-accessibility
или включённая экранная лупа/чтец). Без неё дерево окна почти пустое — тогда честный отказ.
Только нажатие кнопки по имени в окне Яндекс.Музыки; ничего не вводится.
"""
WINDOW_PREFIX = "Яндекс Музыка"
BUTTONS = {
    "shuffle": ("перемешать", "перемешивание", "shuffle", "случайн"),
    "repeat": ("повтор", "repeat"),
}
_BUTTON = 50000
_HYPERLINK = 50005
_INVOKE, _TOGGLE = 10000, 10015
MIN_TREE = 30  # меньше элементов — доступность Chromium выключена

A11Y_HINT = ("Яндекс.Музыка запущена без поддержки кнопок окна. Нажмите «Перезапустить с поддержкой кнопок» "
             "(музыка остановится на пару секунд) — тогда Сакура нажмёт кнопку в окне")


class YmWindowButtons:
    def __init__(self, uia=None):
        self._uia = uia

    @property
    def uia(self):
        if self._uia is None:
            from desktop.core.platform import uia
            self._uia = uia
        return self._uia

    def _window(self):
        return self.uia.window_by_title(WINDOW_PREFIX)

    def _find(self, kind):
        """(кнопка | None, доступность включена)."""
        root = self._window()
        if root is None:
            return None, False
        c = self.uia.client()
        arr = root.FindAll(4, c.CreateTrueCondition())
        if arr.Length < MIN_TREE:
            return None, False
        names = BUTTONS[kind]
        for i in range(min(arr.Length, 5000)):
            el = arr.GetElement(i)
            if el.CurrentControlType == _BUTTON and any(n in (el.CurrentName or "").lower() for n in names):
                return el, True
        return None, True

    def state(self, kind) -> bool | None:
        el, _ = self._find(kind)
        if el is None:
            return None
        unk = el.GetCurrentPattern(_TOGGLE)
        if unk:
            from comtypes.gen.UIAutomationClient import IUIAutomationTogglePattern
            return unk.QueryInterface(IUIAutomationTogglePattern).CurrentToggleState == 1
        aria = (el.CurrentAriaProperties or "").lower()
        if "pressed=true" in aria or "checked=true" in aria:
            return True
        if "pressed=false" in aria or "checked=false" in aria:
            return False
        return None

    def press(self, kind) -> str:
        """'done' | 'no_window' | 'no_a11y' | 'not_found'."""
        el, a11y = self._find(kind)
        if el is None:
            if not a11y:
                return "no_window" if self._window() is None else "no_a11y"
            return "not_found"
        from comtypes.gen.UIAutomationClient import IUIAutomationInvokePattern, IUIAutomationTogglePattern
        unk = el.GetCurrentPattern(_TOGGLE)
        if unk:
            unk.QueryInterface(IUIAutomationTogglePattern).Toggle()
            return "done"
        unk = el.GetCurrentPattern(_INVOKE)
        if unk:
            unk.QueryInterface(IUIAutomationInvokePattern).Invoke()
            return "done"
        return "not_found"

    # ── воспроизведение (music.autoplay): имена из реального дерева приложения 5.122 ──
    def _controls(self):
        root = self._window()
        if root is None:
            return []
        c = self.uia.client()
        arr = root.FindAll(4, c.CreateTrueCondition())
        return [arr.GetElement(i) for i in range(min(arr.Length, 5000))]

    @staticmethod
    def _invoke(el) -> bool:
        from comtypes.gen.UIAutomationClient import IUIAutomationInvokePattern
        unk = el.GetCurrentPattern(_INVOKE)
        if not unk:
            return False
        unk.QueryInterface(IUIAutomationInvokePattern).Invoke()
        return True

    def play_bar(self) -> bool:
        """«Воспроизведение» в панели плеера (между «Предыдущая песня» и «Следующая песня»)."""
        els = self._controls()
        names = [(e.CurrentName or "") for e in els]
        if "Предыдущая песня" not in names:
            return False
        for e in els[names.index("Предыдущая песня") + 1:]:
            if (e.CurrentName or "") == "Воспроизведение" and e.CurrentControlType == _BUTTON:
                return self._invoke(e)
        return False

    def open_link(self, name: str) -> bool:
        """Ссылка боковой панели («Моя волна», «Плейлист Мне нравится») — переход на страницу."""
        for e in self._controls():
            if (e.CurrentName or "") == name and e.CurrentControlType == _HYPERLINK:
                return self._invoke(e)
        return False

    def play_main(self) -> bool:
        """Первая видимая «Воспроизведение» в основной области (до панели плеера)."""
        els = self._controls()
        names = [(e.CurrentName or "") for e in els]
        end = names.index("Предыдущая песня") if "Предыдущая песня" in names else len(els)
        for e in els[:end]:
            if ((e.CurrentName or "") == "Воспроизведение" and e.CurrentControlType == _BUTTON
                    and not e.CurrentIsOffscreen):
                return self._invoke(e)
        return False
