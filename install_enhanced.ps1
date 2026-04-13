# Clawd Code — 增强版一键安装脚本 (Windows PowerShell)
# 借鉴 ClawGod 安装脚本的优秀设计
# 
# 新增功能:
# - 智能检测已有安装
# - 自动备份和还原
# - 双重启动器模式 (clawd + clawd.orig)
# - 配置热注入支持
# - 补丁引擎集成
# - 版本迁移支持
#
# 用法: 
#   powershell -ExecutionPolicy Bypass -File install_enhanced.ps1
#   powershell -ExecutionPolicy Bypass -File install_enhanced.ps1 -Uninstall
#   powershell -ExecutionPolicy Bypass -File install_enhanced.ps1 -DryRun

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$Revert,
    [switch]$DryRun,
    [switch]$Status,
    [string]$Version
)

$ErrorActionPreference = "Stop"

# ===== 颜色函数 (借鉴 ClawGod 的简洁风格) =====
function Write-Info  { param($m) Write-Host "  ✓ $m" -ForegroundColor Green }
function Write-Warn  { param($m) Write-Host "  ✗ $m" -ForegroundColor Red }
function Write-Dim   { param($m) Write-Host "    $m" -ForegroundColor DarkGray }
function Write-Bold  { param($m) Write-Host "  $m" -ForegroundColor Cyan -NoNewline; Write-Host "" }

# ===== 配置 =====
$ProjectName = "Clawd Code"
$InstallDir = Join-Path $env:USERPROFILE ".clawd"
$VenvDir = Join-Path $InstallDir "venv"
$BinDir = Join-Path $env:LOCALAPPDATA "Programs\Python\clawd"
$ClawdBin = Join-Path $BinDir "clawd.cmd"
$ClawdOrigBin = Join-Path $BinDir "clawd.orig.cmd"
$BackupDir = Join-Path $InstallDir "backups"
$PythonMinVersion = "3.10"

Write-Host ""
Write-Bold "  Clawd Code Enhanced Installer"
Write-Host ""

# ===== 卸载逻辑 (借鉴 ClawGod 的防御性设计) =====
if ($Uninstall) {
    Write-Info "开始卸载 Clawd Code..."
    
    # 查找所有可能的安装位置
    $locations = @(
        $BinDir,
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:ProgramFiles "clawd")
    )
    
    foreach ($loc in $locations) {
        if (Test-Path $loc) {
            # 检查是否有原版备份
            $origBin = Join-Path $loc "clawd.orig.cmd"
            if (Test-Path $origBin) {
                # 有备份，还原
                Move-Item -Path $origBin -Destination (Join-Path $loc "clawd.cmd") -Force
                Write-Info "原版 clawd 已还原 ($loc)"
            } elseif (Test-Path (Join-Path $loc "clawd.cmd")) {
                # 检查是否是 Clawd 启动器
                $content = Get-Content (Join-Path $loc "clawd.cmd") -Raw
                if ($content -match "clawd") {
                    Remove-Item (Join-Path $loc "clawd.cmd") -Force
                    Write-Info "已移除 Clawd 启动器 ($loc)"
                }
            }
        }
    }
    
    # 清理安装目录
    if (Test-Path $InstallDir) {
        # 备份用户数据
        $userData = @(
            "features.json",
            "provider.json",
            "runtime_overrides.json"
        )
        
        foreach ($file in $userData) {
            $src = Join-Path $InstallDir $file
            if (Test-Path $src) {
                $dst = Join-Path $BackupDir "uninstall_$(Get-Date -Format 'yyyyMMdd')_$file"
                if (-not (Test-Path $BackupDir)) {
                    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
                }
                Copy-Item -Path $src -Destination $dst -Force
            }
        }
        
        # 删除虚拟环境和缓存
        if (Test-Path $VenvDir) {
            Remove-Item -Path $VenvDir -Recurse -Force
        }
        
        Write-Info "安装目录已清理"
    }
    
    Write-Host ""
    Write-Info "Clawd Code 已卸载"
    Write-Dim "用户配置已备份到: $BackupDir"
    Write-Host ""
    exit 0
}

# ===== 还原逻辑 =====
if ($Revert) {
    Write-Info "开始还原 Clawd Code..."
    
    if (-not (Test-Path $BackupDir)) {
        Write-Warn "没有找到备份目录: $BackupDir"
        exit 1
    }
    
    # 查找最新备份
    $latestBackup = Get-ChildItem -Path $BackupDir -Directory | 
        Sort-Object Name -Descending | 
        Select-Object -First 1
    
    if (-not $latestBackup) {
        Write-Warn "没有找到备份"
        exit 1
    }
    
    Write-Info "从备份还原: $($latestBackup.Name)"
    
    # 还原文件
    Get-ChildItem -Path $latestBackup.FullName -File | ForEach-Object {
        $dst = Join-Path $InstallDir $_.Name
        Copy-Item -Path $_.FullName -Destination $dst -Force
        Write-Info "已还原: $($_.Name)"
    }
    
    Write-Host ""
    Write-Info "还原完成"
    Write-Host ""
    exit 0
}

# ===== 状态检查 =====
if ($Status) {
    Write-Info "Clawd Code 状态检查..."
    Write-Host ""
    
    # Python 版本
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $pyVersion = & $python.Source --version 2>&1
        Write-Info "Python: $pyVersion"
    } else {
        Write-Warn "Python: 未安装"
    }
    
    # 安装目录
    if (Test-Path $InstallDir) {
        $size = (Get-ChildItem $InstallDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
        Write-Info "安装目录: $InstallDir ($([math]::Round($size, 2)) MB)"
    } else {
        Write-Warn "安装目录: 不存在"
    }
    
    # 启动器
    if (Test-Path $ClawdBin) {
        Write-Info "启动器: $ClawdBin"
    } else {
        Write-Warn "启动器: 不存在"
    }
    
    # 原版备份
    if (Test-Path $ClawdOrigBin) {
        Write-Info "原版备份: $ClawdOrigBin"
    } else {
        Write-Dim "原版备份: 不存在"
    }
    
    Write-Host ""
    exit 0
}

# ===== 前置条件检查 =====
Write-Dim "检查前置条件..."

# Python 检查
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}

if (-not $python) {
    Write-Warn "Python 未安装 (需要 >= $PythonMinVersion)"
    Write-Dim "请从 https://python.org 下载"
    exit 1
}

$pythonVersion = & $python.Source --version 2>&1
Write-Info "Python 版本: $pythonVersion"

# 版本检查
$versionMatch = $pythonVersion -match "(\d+)\.(\d+)"
if ($versionMatch) {
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Write-Warn "Python 版本过低 (需要 >= $PythonMinVersion)"
        exit 1
    }
}

# ===== 智能检测已有安装 (借鉴 ClawGod 的智能 PATH 处理) =====
$existingInstall = $null
$installLocations = @(
    $BinDir,
    (Join-Path $env:USERPROFILE ".local\bin"),
    (Get-Command clawd -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source | Split-Path)
)

foreach ($loc in $installLocations) {
    if ($loc -and (Test-Path (Join-Path $loc "clawd.cmd"))) {
        $existingInstall = $loc
        Write-Dim "检测到已有安装: $loc"
        break
    }
}

# ===== 创建目录 =====
Write-Dim "准备安装目录..."

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Info "创建安装目录: $InstallDir"
}

if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
}

# ===== 备份原版 (借鉴 ClawGod 的防御性设计) =====
if (Test-Path $ClawdBin) {
    if (-not (Test-Path $ClawdOrigBin)) {
        if ($DryRun) {
            Write-Dim "[Dry Run] 将备份原版: $ClawdOrigBin"
        } else {
            Copy-Item -Path $ClawdBin -Destination $ClawdOrigBin -Force
            Write-Info "原版已备份: $ClawdOrigBin"
        }
    } else {
        Write-Dim "原版备份已存在"
    }
}

# ===== Dry Run 模式 =====
if ($DryRun) {
    Write-Host ""
    Write-Bold "  Dry Run 模式 - 不执行实际安装"
    Write-Host ""
    Write-Dim "安装目录: $InstallDir"
    Write-Dim "启动器: $ClawdBin"
    Write-Dim "虚拟环境: $VenvDir"
    Write-Host ""
    Write-Info "如需实际安装，请移除 -DryRun 参数"
    Write-Host ""
    exit 0
}

# ===== 安装 Python 依赖 =====
Write-Dim "安装 Python 依赖..."

# 创建虚拟环境
if (-not (Test-Path $VenvDir)) {
    & $python.Source -m venv $VenvDir
    Write-Info "虚拟环境已创建: $VenvDir"
}

# 激活虚拟环境并安装依赖
$activateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    & $activateScript
    
    $pip = Join-Path $VenvDir "Scripts\pip.exe"
    if (Test-Path "requirements.txt") {
        & $pip install -r requirements.txt -q
        Write-Info "Python 依赖已安装"
    }
}

# ===== 创建启动器 (借鉴 ClawGod 的双重启动器模式) =====
Write-Dim "创建启动器..."

$launcherContent = @"
@echo off
REM Clawd Code Launcher (Enhanced)
REM 自动加载配置并启动 Clawd Code

setlocal

REM 设置工作目录
cd /d "%~dp0"

REM 加载环境变量
if exist ".env" (
    for /f "tokens=1,* delims==" %%a in (.env) do (
        set %%a=%%b
    )
)

REM 激活虚拟环境
call "$VenvDir\Scripts\activate.bat"

REM 启动 Clawd Code
python -m src.main %*
"@

$launcherContent | Out-File -FilePath $ClawdBin -Encoding ASCII
Write-Info "启动器已创建: $ClawdBin"

# ===== 创建默认配置 (借鉴 ClawGod 的配置初始化) =====
Write-Dim "创建默认配置..."

# provider.json
$providerJson = @{
    apiKey = ""
    baseURL = "https://api.anthropic.com"
    model = ""
    smallModel = ""
    timeoutMs = 300000
}

$providerPath = Join-Path $InstallDir "provider.json"
if (-not (Test-Path $providerPath)) {
    $providerJson | ConvertTo-Json | Out-File -FilePath $providerPath -Encoding UTF8
    Write-Info "默认 provider.json 已创建"
}

# features.json
$featuresJson = @{
    god_mode = $false
    debug_tracing = $false
    enable_cost_tracking = $true
    enable_chat_summarization = $true
    enable_output_compression = $true
}

$featuresPath = Join-Path $InstallDir "features.json"
if (-not (Test-Path $featuresPath)) {
    $featuresJson | ConvertTo-Json | Out-File -FilePath $featuresPath -Encoding UTF8
    Write-Info "默认 features.json 已创建"
}

# ===== 配置 PATH (借鉴 ClawGod 的智能 PATH 处理) =====
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$BinDir*") {
    Write-Dim ""
    Write-Warn "$BinDir 不在 PATH 中"
    Write-Dim "请手动添加: 设置 -> 系统 -> 关于 -> 高级系统设置 -> 环境变量"
    Write-Dim "或在 PowerShell 中运行:"
    Write-Dim "  `$env:PATH += `";$BinDir`""
    Write-Dim ""
}

# ===== 完成 =====
Write-Host ""
Write-Bold "  Clawd Code Enhanced 已安装!"
Write-Host ""
Write-Dim "  clawd             - 启动 Clawd Code (增强版)"
if (Test-Path $ClawdOrigBin) {
    Write-Dim "  clawd.orig        - 启动原版 Clawd Code"
}
Write-Host ""
Write-Dim "  配置: $InstallDir"
Write-Dim "  provider.json: $providerPath"
Write-Dim "  features.json: $featuresPath"
Write-Host ""
Write-Dim "  如需卸载，请运行:"
Write-Dim "  powershell -ExecutionPolicy Bypass -File install_enhanced.ps1 -Uninstall"
Write-Host ""
