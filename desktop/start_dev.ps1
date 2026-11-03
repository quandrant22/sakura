# Запуск новой Сакуры для работы: ядро (python -m desktop.core --headless) + интерфейс (npm run dev).
#   desktop\start_dev.bat              — обычный запуск
#   desktop\start_dev.ps1 -CheckOnly   — только проверки, ничего не запускает
# Старый агент (agent\sakura.py) и новое ядро делят устройство и микрофон: скрипт не стартует,
# пока старый агент работает, — предлагает его остановить и ждёт ответа «да».
# Секреты: .env не читается и не печатается; проверяется только наличие строк WS_TOKEN и DEVICE_ID.
param(
    [string]$AgentDir = "C:\sakura-git\agent",
    [int]$ReadyTimeoutSec = 120,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$Desktop = $PSScriptRoot
$Repo = Split-Path $Desktop -Parent
$Python = Join-Path $AgentDir "venv\Scripts\python.exe"
$EnvFile = Join-Path $AgentDir ".env"
$DataDir = Join-Path $env:LOCALAPPDATA "Sakura"
$TokenFile = Join-Path $DataDir "ui.token"
$ExtensionPorts = 8766, 8767, 8768, 8769

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }
function Fail($text) { Say "[x] $text" Red; exit 1 }

# ── 1. Старый агент ────────────────────────────────────────────────
function Get-OldAgent {
    $procs = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -match 'agent[\\/]+sakura\.py' -or $_.CommandLine -match '(^|[\s"])sakura\.py' })
    $ports = @(Get-NetTCPConnection -LocalPort $ExtensionPorts -State Listen -ErrorAction SilentlyContinue)
    [pscustomobject]@{ Procs = $procs; Ports = $ports }
}

function Get-NewCore {
    @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'desktop\.core' })
}

$newCore = Get-NewCore
$old = Get-OldAgent
# Порты расширения, занятые не новым ядром.
$foreignPorts = @($old.Ports | Where-Object { $newCore.ProcessId -notcontains $_.OwningProcess })
if ($old.Procs.Count -or $foreignPorts.Count) {
    Say "Похоже, работает старый агент Сакуры:" Yellow
    foreach ($p in $old.Procs) { Say ("  процесс {0} (pid {1})" -f $p.Name, $p.ProcessId) Yellow }
    foreach ($c in $foreignPorts) {
        $owner = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        Say ("  порт {0} занят: {1} (pid {2})" -f $c.LocalPort, $owner.ProcessName, $c.OwningProcess) Yellow
    }
    if ($CheckOnly) { Fail "старый агент работает — запуск невозможен" }
    $answer = Read-Host "Остановить его? Новое ядро и старый агент не могут работать одновременно (да/нет)"
    if ($answer.Trim().ToLower() -ne "да") { Fail "отменено: старый агент не остановлен" }
    $pids = @($old.Procs.ProcessId) + @($foreignPorts | ForEach-Object {
        $o = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        # Порт держит не Python (например, VS Code) — его не трогаем, ядро возьмёт следующий порт.
        if ($o -and $o.ProcessName -like "python*") { $_.OwningProcess }
    }) | Sort-Object -Unique
    foreach ($id in $pids) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue; Say "  остановлен pid $id" }
    Start-Sleep -Seconds 2
    if ((Get-OldAgent).Procs.Count) { Fail "старый агент всё ещё работает" }
}
Say "[ok] старый агент не запущен" Green

# ── 2. Окружение ───────────────────────────────────────────────────
if (-not (Test-Path $Python)) { Fail "нет Python: $Python" }
if (-not (Test-Path $EnvFile)) { Fail "нет файла .env: $EnvFile" }
# Только булева проверка наличия строк; значения не читаются в переменные и не печатаются.
$hasToken = Select-String -Path $EnvFile -Pattern '^\s*WS_TOKEN\s*=\s*\S' -Quiet
$hasDevice = Select-String -Path $EnvFile -Pattern '^\s*DEVICE_ID\s*=\s*\S' -Quiet
Say ("[{0}] WS_TOKEN в .env" -f $(if ($hasToken) { "ok" } else { "x" })) $(if ($hasToken) { "Green" } else { "Red" })
Say ("[{0}] DEVICE_ID в .env" -f $(if ($hasDevice) { "ok" } else { "x" })) $(if ($hasDevice) { "Green" } else { "Red" })
if (-not ($hasToken -and $hasDevice)) { Fail "впишите WS_TOKEN и DEVICE_ID в $EnvFile" }

$env:SAKURA_ENV_FILE = $EnvFile
# Модели не копируются: ядро ищет их в SAKURA_MODELS_DIR (desktop\core\config.py, _find_model).
if (Test-Path (Join-Path $AgentDir "vosk-model-small-ru-0.22")) {
    $env:SAKURA_MODELS_DIR = $AgentDir
    Say "[ok] Vosk small: $AgentDir\vosk-model-small-ru-0.22" Green
} else { Fail "нет модели Vosk small в $AgentDir" }
$giga = Join-Path $env:USERPROFILE ".cache\gigaam"
if (Test-Path (Join-Path $giga "v2_ctc.ckpt")) { Say "[ok] GigaAM: общий кэш $giga" Green }
else { Say "[!] GigaAM в $giga не найден — распознавание откатится на Vosk" Yellow }

if ($CheckOnly) { Say "Проверки пройдены (-CheckOnly: ничего не запущено)." Green; exit 0 }

# ── 3. Ядро ────────────────────────────────────────────────────────
if ($newCore.Count) {
    Say ("[ok] ядро уже запущено (pid {0}) — использую его" -f $newCore[0].ProcessId) Green
} else {
    $started = Get-Date
    $coreProc = Start-Process -FilePath $Python -ArgumentList "-m", "desktop.core", "--headless" `
        -WorkingDirectory $Repo -WindowStyle Minimized -PassThru
    Say "Ядро запускается (окно свёрнуто, лог: $DataDir\logs\sakura.log)…"
    $deadline = $started.AddSeconds($ReadyTimeoutSec)
    while (-not ((Test-Path $TokenFile) -and (Get-Item $TokenFile).LastWriteTime -ge $started.AddSeconds(-1))) {
        if ((Get-Date) -gt $deadline) { Fail "ядро не записало ui.token за $ReadyTimeoutSec с — смотрите $DataDir\logs\sakura.log" }
        if ($coreProc.HasExited) { Fail "ядро завершилось при старте — смотрите $DataDir\logs\sakura.log и crash.log" }
        Start-Sleep -Milliseconds 500
    }
    Say "[ok] ui.token записан — локальный API ядра поднят" Green
}

# ── 4. Интерфейс ───────────────────────────────────────────────────
# VS Code передаёт ELECTRON_RUN_AS_NODE дочерним процессам — Electron стал бы Node.
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) {
    Say "[ok] интерфейс уже запущен (Vite на 5173) — он сам переподключится к ядру" Green
} else {
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run dev" -WorkingDirectory (Join-Path $Desktop "ui") | Out-Null
    Say "Интерфейс запускается (Vite + Electron)…"
}

# ── 5. Пропало ли «Нет связи» ──────────────────────────────────────
# Интерфейс показывает «Нет связи», пока ядро не загружено или сервер недоступен; проверяем то же самое.
Push-Location $Repo
try { $check = & $Python -m desktop.tools.core_check --wait $ReadyTimeoutSec; $ok = $LASTEXITCODE -eq 0 }
finally { Pop-Location }
Say "состояние: $check"
if ($ok) { Say "[ok] ядро готово, сервер на связи — в интерфейсе «Нет связи» пропало" Green }
else { Say "[!] ядро или сервер ещё не на связи — в интерфейсе будет «Нет связи» с пояснением" Yellow; exit 2 }
