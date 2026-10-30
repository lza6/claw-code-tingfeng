# ============================================================================
# 桌面端「装机 E2E」——装 → 真跑 → 重启 → 卸载 → 清残留，一条命令给结论
#
# 为什么要有这个脚本（历史教训）：
#   前几轮的装机验证是**会话里手打的一次性脚本**，跑完就没了 ——
#   于是每轮都要重新拼一遍命令，还重复踩过同样的坑（探针目录/进程自杀/端口就绪竞态）。
#   本脚本把那条链路固化成仓库资产：可重复、有退出码、能进 CI。
#
# 用法：
#   pwsh -NoProfile -File scripts/e2e_desktop_install.ps1                 # 全跑（含安装/卸载）
#   pwsh -NoProfile -File scripts/e2e_desktop_install.ps1 -SkipUi         # 只验 Host 与数据持久化
#   pwsh -NoProfile -File scripts/e2e_desktop_install.ps1 -KeepInstalled  # 跑完不卸载（调试用）
#
# 退出码：0 = 全绿；非 0 = 失败项数量（每个失败都有一行 FAIL 说明）
#
# 前置：本机已有 dist 下的 Setup 包（先跑 prepare_host_bundle.py + build_desktop_signed.ps1）
# ============================================================================
param(
    [switch]$SkipUi,
    [switch]$KeepInstalled,
    [string]$SetupPath = "",
    [int]$LaunchTimeoutSec = 120
)

$ErrorActionPreference = 'Continue'
$failures = New-Object System.Collections.Generic.List[string]
function Say($m) { Write-Output ("[{0:HH:mm:ss}] {1}" -f (Get-Date), $m) }
function Check($name, $ok, $extra = "") {
    if ($ok) { Say "PASS $name$(if ($extra) { " — $extra" })" }
    else {
        Say "FAIL $name$(if ($extra) { " — $extra" })"
        $script:failures.Add($name)
    }
}

$repo = Split-Path -Parent $PSScriptRoot
$projectVersion = (Get-Content (Join-Path $repo 'pyproject.toml') -Raw) -replace '(?s).*?version\s*=\s*"([^"]+)".*', '$1'
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\Clawd Desktop'
$exe = Join-Path $installDir 'Clawd Desktop.exe'
$uninstaller = Join-Path $installDir 'Uninstall Clawd Desktop.exe'
$userData = Join-Path $env:APPDATA 'clawd-desktop'
$dataDir = Join-Path $userData 'data'
$portFile = Join-Path $installDir 'resources\host\.clawd_host_port'
$hostDir = Join-Path $installDir 'resources\host'
$desktop = Join-Path $repo 'desktop'

if (-not $SetupPath) {
    $SetupPath = Get-ChildItem (Join-Path $repo 'desktop\dist') -Filter 'Clawd Desktop Setup *.exe' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $SetupPath -or -not (Test-Path $SetupPath)) {
    Say "FAIL 找不到安装包（先构建）"; exit 1
}

function Stop-AllClawd {
    Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -like '*Clawd Desktop*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

function Get-PortInfo {
    if (-not (Test-Path $portFile)) { return $null }
    try { return Get-Content $portFile -Raw | ConvertFrom-Json } catch { return $null }
}

function Wait-Port([int]$timeoutSec) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        $info = Get-PortInfo
        if ($info) { return $info }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Invoke-Api($info, $path, [switch]$NoToken) {
    $url = "http://127.0.0.1:$($info.port)$path"
    if (-not $NoToken) {
        $sep = if ($path.Contains('?')) { '&' } else { '?' }
        $url = "$url${sep}token=$($info.token)"
    }
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15
        return @{ status = [int]$r.StatusCode; body = $r.Content }
    } catch {
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        return @{ status = $code; body = "$($_.Exception.Message)" }
    }
}

Say "安装包: $SetupPath"
Say "目标版本: $projectVersion"

# ---------------------------------------------------------------- 0. 清理
Say '=== STEP0 清理旧安装与残留进程 ==='
Stop-AllClawd
if (Test-Path $uninstaller) {
    Start-Process $uninstaller -ArgumentList '/S' -Wait | Out-Null
    Start-Sleep -Seconds 3
    Check 'STEP0 旧安装已卸载' (-not (Test-Path $exe))
} else {
    Say 'STEP0 无旧安装'
}

# ---------------------------------------------------------------- 1. 静默安装
Say '=== STEP1 静默安装 ==='
$p = Start-Process $SetupPath -ArgumentList '/S' -PassThru -Wait
Check 'STEP1 安装器退出码 0' ($p.ExitCode -eq 0) "exit=$($p.ExitCode)"
Check 'STEP1 主程序已落盘' (Test-Path $exe) $exe

$pkgVersion = (Get-Content (Join-Path $repo 'desktop\package.json') -Raw | ConvertFrom-Json).version
$exeVersion = if (Test-Path $exe) { (Get-Item $exe).VersionInfo.FileVersion } else { '' }
Check 'STEP1 主程序 FileVersion 与 package.json 一致' ($exeVersion -eq $pkgVersion) "exe=$exeVersion pkg=$pkgVersion"

# 内嵌 host 必须与源码同版本（历史事故：装出来还是旧代码）
if (Test-Path $hostDir) {
    $hostPy = Join-Path $hostDir 'python\python.exe'
    if (Test-Path $hostPy) {
        $hostVer = (& $hostPy -c "import sys; sys.path.insert(0, r'$hostDir'); import src; print(src.__version__)" 2>&1 | Select-Object -Last 1)
        Check 'STEP1 内嵌 host 版本 = 源码版本' ("$hostVer".Trim() -eq $projectVersion) "host=$hostVer src=$projectVersion"
        $promptCount = (Get-ChildItem (Join-Path $hostDir 'prompts\agents') -Filter '*.md' -ErrorAction SilentlyContinue | Measure-Object).Count
        Check 'STEP1 内嵌 prompts/agents 数量 > 0' ($promptCount -gt 0) "count=$promptCount"
    } else {
        Check 'STEP1 内嵌 python 存在' $false $hostPy
    }
} else {
    Check 'STEP1 resources/host 存在' $false $hostDir
}

# ---------------------------------------------------------------- 2. 预置配置 + 首次启动
Say '=== STEP2 预置 .env 并首次启动 ==='
New-Item -ItemType Directory -Force -Path $userData | Out-Null
Copy-Item (Join-Path $repo '.env') (Join-Path $userData '.env') -Force
if (Test-Path $portFile) { Remove-Item $portFile -Force -ErrorAction SilentlyContinue }

$app1 = Start-Process $exe -PassThru
$info = Wait-Port $LaunchTimeoutSec
Check 'STEP2 端口文件出现（Host 起来了）' ($null -ne $info)
$app1.Refresh()
Check 'STEP2 应用进程存活' (-not $app1.HasExited)

if ($info) {
    $home = Invoke-Api $info '/'
    Check 'STEP2 GET / 返回 200' ($home.status -eq 200) "status=$($home.status)"

    $apiInfo = Invoke-Api $info '/api/info'
    Check 'STEP2 /api/info 200' ($apiInfo.status -eq 200) "status=$($apiInfo.status)"

    $providers = Invoke-Api $info '/api/providers'
    Check 'STEP2 /api/providers 200' ($providers.status -eq 200) "status=$($providers.status)"

    $usage = Invoke-Api $info '/api/usage'
    Check 'STEP2 /api/usage 200' ($usage.status -eq 200) "status=$($usage.status)"

    $sessions = Invoke-Api $info '/api/sessions'
    Check 'STEP2 /api/sessions 200' ($sessions.status -eq 200) "status=$($sessions.status)"

    # 数据目录必须与安装目录分离（历史事故：升级即丢配置）
    Check 'STEP2 数据目录已创建（%APPDATA%\clawd-desktop\data）' (Test-Path $dataDir) $dataDir
    # 配置来源：`.env`（预置）或 `<数据目录>/providers.json`（UI 里配过）。两者至少有一个，
    # 否则 Host 起得来但一轮对话都发不出去（"能开不能用"）。
    $hasEnv = Test-Path (Join-Path $userData '.env')
    $hasProv = Test-Path (Join-Path $dataDir 'providers.json')
    Check 'STEP2 配置来源可用（.env 或 providers.json）' ($hasEnv -or $hasProv) "env=$hasEnv providers=$hasProv"

    # 破坏性端点必须鉴权（v0.88.9 的 P0：无 token 可删配置）
    $noTok = Invoke-Api $info '/api/session/delete?id=../providers' -NoToken
    Check 'STEP2 未带 token 的写操作被拒绝（403）' ($noTok.status -eq 403) "status=$($noTok.status)"
}

# ---------------------------------------------------------------- 3. 真浏览器 UI E2E
if (-not $SkipUi -and $info) {
    Say '=== STEP2b 真浏览器 UI E2E（ui_console_e2e.mjs）==='
    $probe = Join-Path $hostDir 'e2e-probe.png'
    Copy-Item (Join-Path $desktop 'screenshots\01-main.png') $probe -Force -ErrorAction SilentlyContinue
    Push-Location $desktop
    try {
        $uiOut = & node ui_console_e2e.mjs --port-file $portFile --img-path 'e2e-probe.png' 2>&1
        $uiExit = $LASTEXITCODE
        $uiOut | Select-Object -Last 6 | ForEach-Object { Say "UI $_" }
        Check 'STEP2b UI E2E 全绿' ($uiExit -eq 0) "exit=$uiExit"
    } catch {
        Check 'STEP2b UI E2E 全绿' $false $_.Exception.Message
    } finally { Pop-Location }
    Remove-Item $probe -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- 4. 重启后数据仍在
Say '=== STEP2c 重启后配置/会话仍在（用户头号投诉回归）==='
taskkill /PID $app1.Id /T /F 2>$null | Out-Null
Start-Sleep -Seconds 3
if (Test-Path $portFile) { Remove-Item $portFile -Force -ErrorAction SilentlyContinue }

$app2 = Start-Process $exe -PassThru
$info2 = Wait-Port $LaunchTimeoutSec
Check 'STEP2c 重启后 Host 再次可用' ($null -ne $info2)
$app2.Refresh()
Check 'STEP2c 重启后应用存活' (-not $app2.HasExited)
if ($info2) {
    $prov2 = Invoke-Api $info2 '/api/providers'
    $provJson = $null
    try { $provJson = $prov2.body | ConvertFrom-Json } catch { }
    Check 'STEP2c 重启后 /api/providers 仍 200' ($prov2.status -eq 200) "status=$($prov2.status)"
    if ($SkipUi) {
        Say 'STEP2c provider 内容校验跳过（-SkipUi：没跑 UI E2E，providers.json 可能尚未生成）'
    } elseif ($provJson -and $provJson.PSObject.Properties.Name -contains 'providers') {
        # 不写 `-ge 0` 这种永真断言：必须是"读得到数组且内容可解析"，
        # 否则"重启后配置丢光"这条历史缺陷会被假绿放过去。
        $provCount = @($provJson.providers).Count
        $provFile = Join-Path $dataDir 'providers.json'
        $provOk = $false
        if (Test-Path $provFile) {
            try { $provOk = (@((Get-Content $provFile -Raw | ConvertFrom-Json).providers).Count -gt 0) } catch { $provOk = $false }
        }
        Check 'STEP2c 重启后 provider 配置仍在（文件非空且接口可读）' ($provOk -and $null -ne $provCount) "count=$provCount file=$provOk"
    } else {
        Check 'STEP2c /api/providers 返回 providers 数组' $false "$($prov2.body)".Substring(0, [Math]::Min(120, "$($prov2.body)".Length))
    }
    $sess2 = Invoke-Api $info2 '/api/sessions'
    Check 'STEP2c 重启后 /api/sessions 200' ($sess2.status -eq 200) "status=$($sess2.status)"
    Check 'STEP2c 重启后数据目录仍存在' (Test-Path (Join-Path $dataDir 'providers.json'))
}

# ---------------------------------------------------------------- 5. 关闭 + 残留检查
Say '=== STEP3 关闭并检查残留 ==='
Stop-AllClawd
$resShell = @(Get-Process 'Clawd Desktop' -ErrorAction SilentlyContinue).Count
$resHost = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -like '*Clawd Desktop*' }).Count
Check 'STEP3 无残留 Electron 进程' ($resShell -eq 0) "count=$resShell"
Check 'STEP3 无残留 Host python 进程' ($resHost -eq 0) "count=$resHost"

# ---------------------------------------------------------------- 6. 卸载 + 残留
if (-not $KeepInstalled) {
    Say '=== STEP4 静默卸载 ==='
    if (Test-Path $uninstaller) {
        $u = Start-Process $uninstaller -ArgumentList '/S' -PassThru -Wait
        Start-Sleep -Seconds 3
        Check 'STEP4 卸载器退出码 0' ($u.ExitCode -eq 0) "exit=$($u.ExitCode)"
        Check 'STEP4 安装目录已删除' (-not (Test-Path $exe))
    } else {
        Check 'STEP4 卸载器存在' $false $uninstaller
    }

    Say '=== STEP5 注册表与快捷方式残留 ==='
    $reg = @(
        (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like '*Clawd*' }).Count,
        (Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like '*Clawd*' }).Count
    ) | Measure-Object -Sum | Select-Object -ExpandProperty Sum
    Check 'STEP5 注册表卸载项残留 0' ($reg -eq 0) "count=$reg"
} else {
    Say '=== STEP4/5 跳过（-KeepInstalled）==='
}

# ---------------------------------------------------------------- 结论
Say ''
Say "==== 装机 E2E 结论：失败 $($failures.Count) 项 ===="
if ($failures.Count -gt 0) { $failures | ForEach-Object { Say "  FAIL $_" } }
exit $failures.Count
