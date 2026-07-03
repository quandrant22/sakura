@echo off
REM ══════════════════════════════════════════════════════════════════
REM  build.bat — сборка агента Сакуры в .exe (PyInstaller)
REM
REM  Запуск: build.bat
REM  Результат: dist/Sakura/Sakura.exe
REM ══════════════════════════════════════════════════════════════════

echo [1/3] Установка зависимостей...
pip install pyinstaller --quiet

echo [2/3] Сборка...
pyinstaller ^
    --name "Sakura" ^
    --onedir ^
    --windowed ^
    --noconfirm ^
    --clean ^
    --icon "extension/icon128.png" ^
    --add-data "extension;extension" ^
    --add-data "vosk-model-small-ru-0.22;vosk-model-small-ru-0.22" ^
    --hidden-import "sounddevice" ^
    --hidden-import "sounddevice._bindings" ^
    --hidden-import "sounddevice._cffi" ^
    --hidden-import "numpy" ^
    --hidden-import "torch" ^
    --hidden-import "whisper" ^
    --hidden-import "vosk" ^
    --hidden-import "silero_vad" ^
    --hidden-import "pynput" ^
    --hidden-import "pynput.mouse._win32" ^
    --hidden-import "pynput.keyboard._win32" ^
    --hidden-import "PyQt6" ^
    --hidden-import "PyQt6.QtCore" ^
    --hidden-import "PyQt6.QtGui" ^
    --hidden-import "PyQt6.QtWidgets" ^
    --hidden-import "pywin32" ^
    --hidden-import "win32gui" ^
    --hidden-import "win32con" ^
    --hidden-import "win32api" ^
    --hidden-import "comtypes" ^
    --hidden-import "pycaw" ^
    --hidden-import "pyautogui" ^
    --hidden-import "pyperclip" ^
    --hidden-import "PIL" ^
    --hidden-import "websockets" ^
    --hidden-import "psutil" ^
    --collect-all "whisper" ^
    --collect-all "vosk" ^
    --collect-all "silero_vad" ^
    --collect-all "sounddevice" ^
    sakura.py

echo [3/3] Готово!
echo ════════════════════════════════════════════════════════════════
echo  Результат: dist\Sakura\Sakura.exe
echo  Все настройки уже внутри config.py — .env не нужен.
echo  Для смены устройства: отредактируй DEVICE_ID в config.py
echo ════════════════════════════════════════════════════════════════
pause
