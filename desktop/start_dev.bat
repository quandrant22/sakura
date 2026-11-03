@echo off
rem Запуск новой Сакуры для работы: ядро + интерфейс. Подробности — start_dev.ps1.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dev.ps1" %*
if errorlevel 1 pause
