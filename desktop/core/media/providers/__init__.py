"""Источники медиа.

Музыка: local (медиатека, library.py), yandex (опция MUSIC_YANDEX=1), remote_smtc
(внешнее приложение через SMTC / Яндекс.Музыку — прежнее поведение агента).
Видео: local (медиатека), youtube_embed (страница IFrame API на media_server),
url_hls (ссылки .mp4/.webm/.m3u8), remote_browser (вкладка браузера через расширение).
"""


class ProviderError(Exception):
    """Понятная пользователю ошибка источника (без секретов в тексте)."""
