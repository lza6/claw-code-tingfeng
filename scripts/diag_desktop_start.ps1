# 诊断：装好的 Clawd Desktop 为什么起不来（只看日志，不猜）
# 用法：pwsh -NoProfile -File scripts/diag_desktop_start.ps1
$ErrorActionPreference = 'Continue'
function Say($msg) { Write-Output $msg }
$repo = Split-Path -Parent $PSScriptRoot
$setup = Join-Path $repo 'desktop\dist\Clawd Desktop Setup 0.86.0.exe'
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\Clawd Desktop'
$exe = Join-Path $installDir 'Clawd Desktop.exe'
$logDir = Join-Path $env:TEMP 'clawd-diag'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir 'stdout.log'
$errLog = Join-Path $logDir 'stderr.log'
Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue

Say '=== 0. 清理旧安装 ==='
Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$uninst = Join-Path $installDir 'Uninstall Clawd Desktop.exe'
if (Test-Path $uninst) { Start-Process -FilePath $uninst -ArgumentList '/S' -Wait | Out-Null; Start-Sleep -Seconds 3 }

Say '=== 1. 静默安装 ==='
if (-not (Test-Path $setup)) { Say "安装包不存在: $setup"; exit 2 }
$p = Start-Process -FilePath $setup -ArgumentList '/S' -Wait -PassThru
Say "install exit=$($p.ExitCode) exe存在=$(Test-Path $exe)"
if (-not (Test-Path $exe)) { exit 3 }

Say '=== 2. 带日志启动（ELECTRON_ENABLE_LOGGING=1）==='
$env:ELECTRON_ENABLE_LOGGING = '1'
$env:ELECTRON_ENABLE_STACK_DUMPING = '1'
$app = Start-Process -FilePath $exe -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Say "pid=$($app.Id)"

$portFile = Join-Path $installDir 'resources\host\.clawd_host_port'
$deadline = (Get-Date).AddSeconds(45)
$got = $false
while ((Get-Date) -lt $deadline) {
  if (Test-Path $portFile) { $got = $true; break }
  Start-Sleep -Milliseconds 800
}
Say "=== 3. 端口文件生成=$got 路径=$portFile ==="
if (Test-Path $portFile) { Say "内容: $(Get-Content $portFile -Raw)" }

$app.Refresh()
Say "窗口标题='$($app.MainWindowTitle)' 存活=$(-not $app.HasExited) 退出码=$(if ($app.HasExited) { $app.ExitCode } else { 'N/A' })"

Say '=== 4. stderr（前 60 行）==='
if (Test-Path $errLog) { Get-Content $errLog -TotalCount 60 | ForEach-Object { Say "ERR $_" } } else { Say 'stderr 为空/缺失' }

Say '=== 5. stdout（前 40 行）==='
if (Test-Path $outLog) { Get-Content $outLog -TotalCount 40 | ForEach-Object { Say "OUT $_" } } else { Say 'stdout 为空/缺失' }

Say '=== 6. 数据目录内容 ==='
$dataDir = Join-Path $env:APPDATA 'Clawd Desktop\data'
if (Test-Path $dataDir) { Get-ChildItem $dataDir | ForEach-Object { Say "DATA $($_.Name)" } } else { Say '数据目录不存在' }

Say '=== 6b. 壳日志（shell.log 最近 40 行）==='
$shellLog = Join-Path $env:APPDATA 'Clawd Desktop\shell.log'
if (Test-Path $shellLog) { Get-Content $shellLog -Tail 40 | ForEach-Object { Say "SHELL $_" } } else { Say 'shell.log 不存在（主进程还没走到 slog）' }

Say '=== 7. 关闭 + 卸载 ==='
Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
if (Test-Path $uninst) { Start-Process -FilePath $uninst -ArgumentList '/S' -Wait | Out-Null }
Say 'DONE'
