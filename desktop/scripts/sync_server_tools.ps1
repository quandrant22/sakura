# Обновить desktop/tests/fixtures/server_tools.json из выгрузки сервера одной командой:
#   powershell -File desktop\scripts\sync_server_tools.ps1 [-Ref origin/server/browser-step]
# Берёт tests/fixtures/server_tools.json ветки сервера (git cat-file) байт в байт, без правок,
# и проверяет, что blob в рабочей копии совпал с серверным. Секреты не читает.
param([string]$Ref = "origin/server/browser-step")

$ErrorActionPreference = "Stop"
$Src = "tests/fixtures/server_tools.json"
$Root = (git rev-parse --show-toplevel).Trim()
$Rel = "desktop/tests/fixtures/server_tools.json"
$Dst = Join-Path $Root $Rel

if ($Ref -like "origin/*") {
    git -C $Root fetch --quiet origin $Ref.Substring(7)
    if ($LASTEXITCODE -ne 0) { throw "git fetch $Ref не удался" }
}
$Want = (git -C $Root rev-parse "${Ref}:$Src").Trim()
if ($LASTEXITCODE -ne 0) { throw "в $Ref нет $Src" }

# Перенаправление PowerShell перекодирует текст — байты пишет cmd.
cmd /c "git -C `"$Root`" cat-file blob $Want > `"$Dst.tmp`""
if ($LASTEXITCODE -ne 0) { throw "git cat-file не удался" }
Move-Item -Force "$Dst.tmp" $Dst

$Got = (git -C $Root hash-object --path $Rel $Dst).Trim()
if ($Got -ne $Want) { throw "server_tools.json: blob $Got не совпал с $Ref ($Want)" }
$Short = (git -C $Root rev-parse --short $Ref).Trim()
Write-Output "server_tools.json <- $Ref ($Short, blob $($Want.Substring(0, 7)))"
