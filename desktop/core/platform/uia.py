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
