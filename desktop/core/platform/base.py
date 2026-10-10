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
