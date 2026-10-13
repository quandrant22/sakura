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
_INVOKE, _TOGGLE = 10000, 10015
MIN_TREE = 30  # меньше элементов — доступность Chromium выключена

A11Y_HINT = ("в приложении Яндекс.Музыки выключена доступность для программ. Закройте приложение и "
             "запустите его с ключом --force-renderer-accessibility (ярлык → Свойства → Объект) — "
             "тогда Сакура нажмёт кнопку в окне")


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
