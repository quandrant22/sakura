# Ярлык «Sakura» на рабочем столе и в меню «Пуск» (запуск без консоли через Sakura.vbs, иконка цветка).
#   desktop\tools\make_shortcut.ps1                — рабочий стол и «Пуск»
#   desktop\tools\make_shortcut.ps1 -Autostart     — плюс автозапуск при входе в Windows
#   desktop\tools\make_shortcut.ps1 -NoAutostart   — убрать ярлык автозапуска
#   -DesktopOnly                                    — только рабочий стол
param([switch]$Autostart, [switch]$NoAutostart, [switch]$DesktopOnly)

$ErrorActionPreference = "Stop"
$Desktop = Split-Path $PSScriptRoot -Parent
$Vbs = Join-Path $Desktop "Sakura.vbs"
$Icon = Join-Path $Desktop "assets\sakura.ico"
if (-not (Test-Path $Vbs)) { throw "нет $Vbs" }
if (-not (Test-Path $Icon)) { throw "нет иконки $Icon — выполните python -m desktop.tools.make_icon" }

function New-SakuraShortcut([string]$Path) {
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut($Path)
    $lnk.TargetPath = Join-Path $env:WINDIR "System32\wscript.exe"
    $lnk.Arguments = '"' + $Vbs + '"'
    $lnk.WorkingDirectory = $Desktop
    $lnk.IconLocation = "$Icon,0"
    $lnk.Description = "Сакура — голосовой помощник"
    $lnk.Save()
    Write-Output $Path
}

New-SakuraShortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "Sakura.lnk")
if (-not $DesktopOnly) {
    New-SakuraShortcut (Join-Path ([Environment]::GetFolderPath("Programs")) "Sakura.lnk")
}
$startup = Join-Path ([Environment]::GetFolderPath("Startup")) "Sakura.lnk"
if ($Autostart) { New-SakuraShortcut $startup }
if ($NoAutostart -and (Test-Path $startup)) { Remove-Item $startup; Write-Output "автозапуск убран: $startup" }
