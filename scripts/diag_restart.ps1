# 诊断：安装后"重启应用"为什么 exit 1（只观察，不猜）
# 用法：pwsh -NoProfile -File scripts/diag_restart.ps1
$ErrorActionPreference = 'Continue'
function Say($m) { Write-Output ("[{0:HH:mm:ss}] {1}" -f (Get-Date), $m) }
$repo = Split-Path -Parent $PSScriptRoot
$setup = Join-Path $repo 'desktop\dist\Clawd Desktop Setup 0.86.0.exe'
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\Clawd Desktop'
$exe = Join-Path $installDir 'Clawd Desktop.exe'
$userData = Join-Path $env:APPDATA 'clawd-desktop'
$portFile = Join-Path $installDir 'resources\host\.clawd_host_port'
$out = Join-Path $env:TEMP 'clawd-diag-restart'
New-Item -ItemType Directory -Force -Path $out | Out-Null

Say '=== 0. 清理 ==='
Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.ExecutablePath -like '*Clawd Desktop*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$uninst = Join-Path $installDir 'Uninstall Clawd Desktop.exe'
if (Test-Path $uninst) { Start-Process $uninst -ArgumentList '/S' -Wait | Out-Null; Start-Sleep 3 }

Say '=== 1. 安装 ==='
Start-Process $setup -ArgumentList '/S' -Wait | Out-Null
Say "exe存在=$(Test-Path $exe)"

Say '=== 2. 预置 .env（跳过首次配置）==='
New-Item -ItemType Directory -Force -Path $userData | Out-Null
Copy-Item (Join-Path $repo '.env') (Join-Path $userData '.env') -Force
Say '已写入 .env'

Say '=== 3. 第一次启动 ==='
$p1 = Start-Process $exe -PassThru
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline -and -not (Test-Path $portFile)) { Start-Sleep -Milliseconds 500 }
Say "第一次: 端口文件=$(Test-Path $portFile) pid=$($p1.Id) 存活=$(-not $p1.HasExited)"

Say '=== 4. 杀掉第一次（模拟用户重启）==='
taskkill /PID $p1.Id /T /F 2>$null | Out-Null
Start-Sleep -Seconds 3
if (Test-Path $portFile) { Remove-Item $portFile -Force }
Say "残留 Clawd 进程=$((Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Measure-Object).Count)"
Say "残留 host python=$((Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ExecutablePath -like '*Clawd Desktop*' } | Measure-Object).Count)"

Say '=== 5. 第二次启动并逐秒观察（关键）==='
$errLog = Join-Path $out 'app2-stderr.log'
$outLog = Join-Path $out 'app2-stdout.log'
Remove-Item $errLog, $outLog -Force -ErrorAction SilentlyContinue
$env:ELECTRON_ENABLE_LOGGING = '1'
$p2 = Start-Process $exe -PassThru -RedirectStandardError $errLog -RedirectStandardOutput $outLog
$start = Get-Date
$didHttp = $false
for ($i = 1; $i -le 120; $i++) {
  Start-Sleep -Seconds 1
  $p2.Refresh()
  $alive = -not $p2.HasExited
  $procs = (Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Measure-Object).Count
  $pf = Test-Path $portFile
  # t+30s 时做一次和 E2E 相同的 HTTP 请求，验证"请求本身会不会打死进程"
  if ($i -eq 30 -and -not $didHttp -and (Test-Path $portFile)) {
    try {
      $info = Get-Content $portFile -Raw | ConvertFrom-Json
      $r = Invoke-WebRequest -Uri ("http://127.0.0.1:$($info.port)/api/providers") -UseBasicParsing -TimeoutSec 20
      Say "t+30s HTTP /api/providers -> $($r.StatusCode)"
    } catch { Say "t+30s HTTP 失败: $($_.Exception.Message)" }
    $didHttp = $true
  }
  if (-not $alive -or $i % 10 -eq 0) {
    Say ("t+{0}s 存活={1} 退出码={2} 同进程数={3} 端口文件={4}" -f $i, $alive, $(if ($p2.HasExited) { $p2.ExitCode } else { 'N/A' }), $procs, $pf)
  }
  if ($p2.HasExited) { break }
}

Say '=== 6. 证据 ==='
Say "stderr 大小=$((Get-Item $errLog -ErrorAction SilentlyContinue).Length) bytes"
if (Test-Path $errLog) { Get-Content $errLog -Tail 30 | ForEach-Object { Say "ERR $_" } }
$crash = Join-Path $userData 'Crashpad'
Say "Crashpad 存在=$(Test-Path $crash)"
$shellLog = Join-Path $userData 'shell.log'
if (Test-Path $shellLog) { Get-Content $shellLog -Tail 25 | ForEach-Object { Say "SHELL $_" } }
Say '--- Windows 应用错误事件（最近 3 条）---'
try {
  Get-WinEvent -FilterHashtable @{ LogName = 'Application'; Level = 2 } -MaxEvents 3 -ErrorAction Stop |
    ForEach-Object { Say ("EVT {0} {1}" -f $_.TimeCreated, ($_.Message -split "`n")[0..2] -join ' | ') }
} catch { Say "读取事件日志失败: $($_.Exception.Message)" }

Say '=== 7. 收尾 ==='
Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 2
if (Test-Path $uninst) { Start-Process $uninst -ArgumentList '/S' -Wait | Out-Null }
Say 'DONE'
