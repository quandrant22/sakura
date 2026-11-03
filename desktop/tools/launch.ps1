# Запуск Сакуры двойным щелчком (Sakura.vbs → этот скрипт без окна консоли).
# Проверки с понятными диалогами, при необходимости один раз npm install и сборка (окно прогресса),
# затем готовая сборка Electron; ядро запускает само окно (SAKURA_CORE_AUTOSTART=1) и закрывает при выходе.
# Секреты: .env не читается в переменные и не печатается — только булева проверка строк.
param(
    [string]$AgentDir = "C:\sakura-git\agent",
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$Desktop = Split-Path $PSScriptRoot -Parent
$Repo = Split-Path $Desktop -Parent
$Ui = Join-Path $Desktop "ui"
$Python = Join-Path $AgentDir "venv\Scripts\python.exe"
$EnvFile = if ($env:SAKURA_ENV_FILE) { $env:SAKURA_ENV_FILE } else { Join-Path $AgentDir ".env" }
$DataDir = Join-Path $env:LOCALAPPDATA "Sakura"
$LogDir = Join-Path $DataDir "logs"
$LauncherLog = Join-Path $LogDir "launcher.log"
$Electron = Join-Path $Ui "node_modules\electron\dist\electron.exe"
$ExtensionPorts = 8766, 8767, 8768, 8769

New-Item -ItemType Directory -Force $LogDir | Out-Null
Add-Type -AssemblyName System.Windows.Forms

function Log($text) { Add-Content -Path $LauncherLog -Value ("{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $text) -Encoding UTF8 }
function Ask($text) {
    $r = [System.Windows.Forms.MessageBox]::Show($text, "Сакура", "YesNo", "Question")
    return $r -eq [System.Windows.Forms.DialogResult]::Yes
}
function Fail($text) {
    Log "ошибка: $text"
    [System.Windows.Forms.MessageBox]::Show("$text`n`nЖурнал запуска: $LauncherLog", "Сакура не запустилась", "OK", "Error") | Out-Null
    exit 1
}

Log "запуск: $Desktop"

# ── Уже открыта — второй экземпляр Electron просто покажет существующее окно ──
$running = @(Get-CimInstance Win32_Process -Filter "Name='electron.exe'" | Where-Object { $_.ExecutablePath -eq $Electron })
if ($running.Count -and -not $CheckOnly) {
    Log "Сакура уже запущена (pid $($running[0].ProcessId)) — показываю окно"
    Start-Process -FilePath $Electron -ArgumentList "." -WorkingDirectory $Ui
    exit 0
}

# ── 1. Node, Python, .env ──────────────────────────────────────────
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Fail "Не найден Node.js. Установите Node.js LTS с nodejs.org и запустите Сакуру снова." }
if (-not (Test-Path $Python)) { Fail "Не найден Python агента: $Python`nВосстановите окружение: в папке $AgentDir выполните python -m venv venv и установите зависимости." }
if (-not (Test-Path $EnvFile)) { Fail "Не найден файл настроек $EnvFile`nСкопируйте его из резервной копии или создайте по образцу .env.example." }
# Только булева проверка наличия строк; значения не читаются в переменные.
$hasToken = Select-String -Path $EnvFile -Pattern '^\s*WS_TOKEN\s*=\s*\S' -Quiet
$hasDevice = Select-String -Path $EnvFile -Pattern '^\s*DEVICE_ID\s*=\s*\S' -Quiet
if (-not ($hasToken -and $hasDevice)) { Fail "В $EnvFile нет строк WS_TOKEN и DEVICE_ID.`nВпишите их (Настройки → Секреты или Блокнот) и запустите снова." }
Log "проверки: node, python, .env — ok"

# ── 2. Старый агент ────────────────────────────────────────────────
$old = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match 'agent[\\/]+sakura\.py' -or $_.CommandLine -match '(^|[\s"])sakura\.py' })
if ($old.Count) {
    if ($CheckOnly) { Fail "Работает старый агент Сакуры (pid $($old[0].ProcessId))." }
    if (-not (Ask "Работает старый агент Сакуры. Новая Сакура и старый агент не могут работать одновременно (общий микрофон и устройство).`n`nЗакрыть старый агент?")) {
        Log "отменено: старый агент не закрыт"
        exit 0
    }
    foreach ($p in $old) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; Log "старый агент остановлен: pid $($p.ProcessId)" }
    Start-Sleep -Seconds 2
}

# ── 2а. Лишние ядра: окна Сакуры нет, значит любое desktop.core — осиротевшее (закрыть деревом) ──
$cores = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match '-m\s+desktop\.core' })
# venv\Scripts\python.exe — запускатель: настоящий интерпретатор — его дочерний процесс; закрываем корни.
$roots = @($cores | Where-Object { $cores.ProcessId -notcontains $_.ParentProcessId })
foreach ($c in $roots) {
    if ($CheckOnly) { Log "найдено лишнее ядро pid $($c.ProcessId) (-CheckOnly: не закрываю)"; continue }
    & taskkill.exe /PID $c.ProcessId /T /F | Out-Null
    Log "закрыто лишнее ядро pid $($c.ProcessId) (запущено $($c.CreationDate)): $($c.CommandLine)"
}
if ($roots.Count -and -not $CheckOnly) { Start-Sleep -Seconds 1 }

# ── 3. Зависимости и сборка (один раз; повторно — если исходники новее сборки) ──
function Newest($paths) {
    $t = [datetime]::MinValue
    foreach ($p in $paths) {
        if (Test-Path $p -PathType Container) {
            $f = Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($f -and $f.LastWriteTime -gt $t) { $t = $f.LastWriteTime }
        } elseif (Test-Path $p) {
            $w = (Get-Item $p).LastWriteTime
            if ($w -gt $t) { $t = $w }
        }
    }
    return $t
}
$lock = Join-Path $Ui "package-lock.json"
$installed = Join-Path $Ui "node_modules\.package-lock.json"
$needInstall = -not (Test-Path $Electron) -or -not (Test-Path $installed) -or ((Test-Path $lock) -and (Get-Item $lock).LastWriteTime -gt (Get-Item $installed).LastWriteTime)
$built = @((Join-Path $Ui "dist\index.html"), (Join-Path $Ui "dist-electron\main.js"))
$sources = @("src", "electron", "index.html", "package.json", "vite.config.ts", "tsconfig.json", "tsconfig.electron.json",
    "tailwind.config.js", "postcss.config.js") | ForEach-Object { Join-Path $Ui $_ }
$needBuild = $needInstall -or ($built | Where-Object { -not (Test-Path $_) }).Count -gt 0
if (-not $needBuild) {
    $oldest = ($built | ForEach-Object { (Get-Item $_).LastWriteTime } | Sort-Object | Select-Object -First 1)
    $needBuild = (Newest $sources) -gt $oldest
}
Log ("сборка: install={0} build={1}" -f $needInstall, $needBuild)
if ($CheckOnly) { Log "проверки пройдены (-CheckOnly)"; Write-Output "ok install=$needInstall build=$needBuild"; exit 0 }

if ($needInstall -or $needBuild) {
    $buildLog = Join-Path $LogDir "build.log"
    $steps = @()
    if ($needInstall) { $steps += "npm install" }
    $steps += "npm run build"
    $cmd = "`$host.UI.RawUI.WindowTitle = 'Сакура — подготовка к первому запуску (это один раз)'; " +
        "Write-Host 'Сакура готовится к запуску: устанавливаю и собираю интерфейс. Окно закроется само.' -ForegroundColor Magenta; " +
        "Set-Location '$Ui'; " +
        (($steps | ForEach-Object { "& cmd /c '$_ 2>&1' | Tee-Object -FilePath '$buildLog' -Append; if (`$LASTEXITCODE) { exit `$LASTEXITCODE }" }) -join "; ")
    $p = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd -Wait -PassThru
    if ($p.ExitCode -ne 0) { Fail "Не удалось подготовить интерфейс ($($steps -join ', ')).`nПодробности: $buildLog" }
    Log "сборка готова"
}

# ── 4. Запуск: готовая сборка, ядро — дочерним процессом окна ────────
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Remove-Item Env:SAKURA_DEV_URL -ErrorAction SilentlyContinue
$env:SAKURA_CORE_AUTOSTART = "1"
$env:SAKURA_PYTHON = $Python
$env:SAKURA_ENV_FILE = $EnvFile
$env:SAKURA_REPO_DIR = $Repo
if (Test-Path (Join-Path $AgentDir "vosk-model-small-ru-0.22")) { $env:SAKURA_MODELS_DIR = $AgentDir }
$marker = Join-Path $DataDir "update_pending.json"
$started = Get-Date
$app = Start-Process -FilePath $Electron -ArgumentList "." -WorkingDirectory $Ui -PassThru
Log "окно запущено: pid $($app.Id)"

# ── Первый запуск после обновления: ядро не поднялось за 90 с — откат на прежнюю версию ──
if (Test-Path $marker) {
    $tokenFile = Join-Path $DataDir "ui.token"
    $deadline = $started.AddSeconds(90)
    while ((Test-Path $marker) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    if (Test-Path $marker) {
        $prev = (Get-Content $marker -Raw -Encoding UTF8 | ConvertFrom-Json).prev
        Log "после обновления ядро не поднялось за 90 с — откат на $prev"
        & $Electron "." "--quit" | Out-Null
        Start-Sleep -Seconds 5
        & git -C $Repo reset --keep $prev 2>&1 | ForEach-Object { Log "git: $_" }
        Push-Location $Ui; & cmd /c "npm run build >> `"$(Join-Path $LogDir 'build.log')`" 2>&1"; Pop-Location
        Remove-Item $marker -ErrorAction SilentlyContinue
        [System.Windows.Forms.MessageBox]::Show("Новая версия Сакуры не запустилась — вернула прежнюю.`n`nПодробности: $LauncherLog", "Сакура", "OK", "Warning") | Out-Null
        $app = Start-Process -FilePath $Electron -ArgumentList "." -WorkingDirectory $Ui -PassThru
        Log "прежняя версия запущена: pid $($app.Id)"
    }
}
Start-Sleep -Seconds 5
if ($app.HasExited -and $app.ExitCode -ne 0) { Fail "Окно Сакуры закрылось сразу после запуска (код $($app.ExitCode))." }
exit 0
