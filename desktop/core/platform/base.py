"""desktop.core.platform.base — интерфейс платформенного слоя.

Всё, что зависит от ОС (громкость, окна, горячие клавиши, простой пользователя,
автозапуск, захват системного звука, питание), живёт только в реализациях
этого класса. Остальное ядро вызывает методы Platform и не трогает WinAPI.
"""
from abc import ABC, abstractmethod


class Platform(ABC):
    name: str = "base"

    # ── громкость и медиа ──────────────────────────────────────────
    @abstractmethod
    def get_volume(self) -> int:
        """Текущая громкость системы, 0..100."""

    @abstractmethod
    def set_volume(self, percent: int) -> int:
        """Установить громкость 0..100, вернуть итоговое значение."""

    @abstractmethod
    def nudge_volume(self, delta: int) -> int:
        """Сдвинуть громкость на delta процентов, вернуть итоговое значение."""

    @abstractmethod
    def app_volume_get(self, names: tuple[str, ...]) -> int | None:
        """Громкость звуковой сессии приложения (0..100) по части имени процесса; None — сессии нет."""

    @abstractmethod
    def app_volume_set(self, names: tuple[str, ...], percent: int) -> int | None:
        """Установить громкость сессии приложения 0..100; итог или None — сессии нет."""

    @abstractmethod
    def media_key(self, kind: str) -> None:
        """Медиаклавиша: play_pause, next, prev, mute, volume_up, volume_down."""

    # ── окна и ввод ────────────────────────────────────────────────
    @abstractmethod
    def active_window(self) -> dict:
        """{'title', 'process', 'pid'} активного окна."""

    @abstractmethod
    def focus_window(self, query: str) -> bool:
        """Вывести на передний план окно по части заголовка или имени процесса."""

    @abstractmethod
    def close_window(self, query: str) -> bool:
        """Закрыть окно по части заголовка или имени процесса."""

    @abstractmethod
    def close_browser_window(self) -> str | None:
        """Закрыть верхнее окно браузера (по процессу и классу окна); заголовок закрытого или None."""

    @abstractmethod
    def press_virtual_key(self, vk: int, hold: float = 0.0) -> bool:
        """Нажать и отпустить виртуальную клавишу (медиаклавиши и т.п.); False — не удалось."""

    @abstractmethod
    def activate_window_handle(self, hwnd: int) -> bool:
        """Вывести окно по его хэндлу на передний план; True — окно стало активным."""

    @abstractmethod
    def hotkey(self, combo: str) -> None:
        """Нажать сочетание клавиш, например 'ctrl+shift+t'."""

    @abstractmethod
    def type_text(self, text: str) -> None:
        """Напечатать текст в активное окно."""

    @abstractmethod
    def idle_seconds(self) -> float:
        """Секунды без ввода; при ошибке — большое число."""

    # ── окна (п. 2.3) ──────────────────────────────────────────────
    @abstractmethod
    def windows(self) -> list[dict]:
        """Видимые окна верхнего уровня, верхнее первым: [{'hwnd', 'title', 'process'}]."""

    @abstractmethod
    def foreground_window(self) -> dict | None:
        """Активное окно {'hwnd', 'title', 'process'} или None."""

    @abstractmethod
    def window_show(self, hwnd: int, state: str) -> bool:
        """state: minimize | maximize | restore."""

    @abstractmethod
    def window_snap(self, hwnd: int, side: str) -> bool:
        """Прижать окно к половине (left/right) или во весь экран сверху (top) его монитора."""

    @abstractmethod
    def window_to_monitor(self, hwnd: int, target: str) -> bool:
        """Перенести окно на монитор: next или номер с 1."""

    # ── экран, звук, сеть, файлы (п. 2.3) ──────────────────────────
    @abstractmethod
    def display_off(self) -> None:
        """Погасить экран (без блокировки и сна)."""

    @abstractmethod
    def set_brightness(self, percent: int) -> bool:
        """Яркость встроенного экрана 0..100; False — монитор не поддерживает (внешний без DDC)."""

    @abstractmethod
    def mic_mute(self, mute: bool | None) -> bool | None:
        """Системный микрофон: True — выключить, False — включить, None — переключить. Итог (muted) или None."""

    @abstractmethod
    def radio(self, kind: str, on: bool) -> bool:
        """Wi-Fi или Bluetooth (kind: wifi | bluetooth) вкл/выкл без прав администратора."""

    @abstractmethod
    def restore_from_recycle(self, path: str) -> bool:
        """Вернуть файл из корзины на прежнее место."""
        raise NotImplementedError

    @abstractmethod
    def recycle(self, path: str) -> bool:
        """Удалить файл или папку только в корзину (с возможностью вернуть)."""

    @abstractmethod
    def reveal(self, path: str) -> bool:
        """Показать файл в проводнике (выделить)."""

    @abstractmethod
    def focused_is_password(self) -> bool:
        """Фокус ввода — поле пароля (UI Automation IsPassword); при сомнении — True."""

    # ── система ────────────────────────────────────────────────────
    @abstractmethod
    def autostart_get(self) -> bool:
        """Включён ли автозапуск для текущего пользователя."""

    @abstractmethod
    def autostart_set(self, enabled: bool, command: str) -> None:
        """Включить/выключить автозапуск команды для текущего пользователя."""

    @abstractmethod
    def power(self, action: str) -> None:
        """lock, sleep, shutdown, restart, shutdown_cancel."""

    @abstractmethod
    def restrict_to_current_user(self, path: str) -> None:
        """Оставить доступ к файлу только текущему пользователю (токен локального API)."""

    @abstractmethod
    def steam_path(self) -> str | None:
        """Папка установки Steam (для сканирования игр) или None."""

    @abstractmethod
    def open_path(self, target: str) -> bool:
        """Открыть файл, ярлык, URL или программу средствами ОС."""

    @abstractmethod
    def system_audio_loopback(self):
        """Источник системного звука (loopback) для эквалайзера; None — недоступно."""


def interface_methods() -> set[str]:
    """Имена абстрактных методов — для теста совпадения реализаций."""
    return set(Platform.__abstractmethods__)
