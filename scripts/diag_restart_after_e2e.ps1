# 诊断（复刻 E2E 场景）：装 → 跑 Playwright 27 项 → 杀掉 → 重启，逐秒观察
# 目的：干净环境重启 120s 不挂（diag_restart.ps1 已证），但 E2E 里 app2 立刻挂。
#      差别就在"第一次实例上跑过 Playwright 并写了项目/用量"。本脚本验证这个差别。
# 用法：pwsh -NoProfile -File scripts/diag_restart_after_e2e.ps1
$ErrorActionPreference = 'Continue'
function Say($m) { Write-Output ("[{0:HH:mm:ss}] {1}" -f (Get-Date), $m) }
$repo = Split-Path -Parent $PSScriptRoot
# 取 dist 下最新的 Setup 包（不写死版本号）
$setup = Get-ChildItem (Join-Path $repo 'desktop\dist') -Filter 'Clawd Desktop Setup *.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\Clawd Desktop'
$exe = Join-Path $installDir 'Clawd Desktop.exe'
$userData = Join-Path $env:APPDATA 'clawd-desktop'
$portFile = Join-Path $installDir 'resources\host\.clawd_host_port'
$desktop = Join-Path $repo 'desktop'

Say '=== 0. 清理 ==='
Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.ExecutablePath -like '*Clawd Desktop*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$uninst = Join-Path $installDir 'Uninstall Clawd Desktop.exe'
if (Test-Path $uninst) { Start-Process $uninst -ArgumentList '/S' -Wait | Out-Null; Start-Sleep 3 }

Say '=== 1. 安装 + 预置 .env ==='
Start-Process $setup -ArgumentList '/S' -Wait | Out-Null
New-Item -ItemType Directory -Force -Path $userData | Out-Null
Copy-Item (Join-Path $repo '.env') (Join-Path $userData '.env') -Force

Say '=== 2. 第一次启动 ==='
$p1 = Start-Process $exe -PassThru
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline -and -not (Test-Path $portFile)) { Start-Sleep -Milliseconds 500 }
Say "第一次: 端口文件=$(Test-Path $portFile) pid=$($p1.Id)"

Say '=== 3. 跑 Playwright 27 项（复刻 E2E 对第一个实例做的事）==='
Push-Location $desktop
try {
  Copy-Item (Join-Path $desktop (Join-Path 'screenshots' '01-main.png')) (Join-Path $installDir (Join-Path 'resources\host' 'e2e-probe.png')) -Force -ErrorAction SilentlyContinue
  $ce = node ui_console_e2e.mjs --port-file $portFile --img-path 'e2e-probe.png' 2>&1
  $tail = $ce | Select-Object -Last 4
  $tail | ForEach-Object { Say "E2E $_" }
  Say "E2E exit=$LASTEXITCODE"
} catch { Say "E2E ERR $($_.Exception.Message)" }
Pop-Location

$p1.Refresh()
Say "跑完 E2E 后第一次实例: 存活=$(-not $p1.HasExited) 退出码=$(if ($p1.HasExited) { $p1.ExitCode } else { 'N/A' })"

Say '=== 4. 杀掉第一次 ==='
taskkill /PID $p1.Id /T /F 2>$null | Out-Null
Start-Sleep -Seconds 3
if (Test-Path $portFile) { Remove-Item $portFile -Force }
Say "残留 Clawd=$((Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Measure-Object).Count) 残留 host python=$((Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ExecutablePath -like '*Clawd Desktop*' } | Measure-Object).Count)"

Say '=== 5. 第二次启动，逐秒观察 60s ==='
$errLog = Join-Path $env:TEMP 'clawd-diag2-stderr.log'
$outLog = Join-Path $env:TEMP 'clawd-diag2-stdout.log'
Remove-Item $errLog, $outLog -Force -ErrorAction SilentlyContinue
$env:ELECTRON_ENABLE_LOGGING = '1'
$p2 = Start-Process $exe -PassThru -RedirectStandardError $errLog -RedirectStandardOutput $outLog
for ($i = 1; $i -le 60; $i++) {
  Start-Sleep -Seconds 1
  $p2.Refresh()
  if ($p2.HasExited) { Say ("t+{0}s 已退出，退出码={1}" -f $i, $p2.ExitCode); break }
  if ($i % 10 -eq 0) {
    $pf = Test-Path $portFile
    Say ("t+{0}s 存活 端口文件={1} 同进程={2}" -f $i, $pf, (Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Measure-Object).Count)
  }
}

Say '=== 6. 证据 ==='
Say "stderr=$((Get-Item $errLog -ErrorAction SilentlyContinue).Length)B stdout=$((Get-Item $outLog -ErrorAction SilentlyContinue).Length)B"
$shellLog = Join-Path $userData 'shell.log'
if (Test-Path $shellLog) {
  Get-Content $shellLog -Tail 15 | Where-Object { $_ -notmatch 'websockets|connection |EOFError|Traceback|  File |raise |^$|The above' } | ForEach-Object { Say "SHELL $_" }
}

Say '=== 7. 收尾 ==='
Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 2
if (Test-Path $uninst) { Start-Process $uninst -ArgumentList '/S' -Wait | Out-Null }
Say 'DONE'
