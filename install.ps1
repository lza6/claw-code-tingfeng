# Clawd Code — 一键安装脚本 (Windows PowerShell)
# Inspired by Project B (ClawGod)'s install.ps1
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$Revert,
    [switch]$Status,
    [string]$Version
)

$ErrorActionPreference = "Stop"

# ===== 颜色函数 =====
function Write-Info  { Write-Host "[INFO] $($args -join ' ')" -ForegroundColor Cyan }
function Write-Ok    { Write-Host "[OK] $($args -join ' ')" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN] $($args -join ' ')" -ForegroundColor Yellow }
function Write-Error { Write-Host "[ERROR] $($args -join ' ')" -ForegroundColor Red }

# ===== 配置 =====
$ProjectName = "Clawd Code"
$InstallDir = Join-Path $env:USERPROFILE ".clawd"
$VenvDir = Join-Path $InstallDir "venv"
$BinDir = Join-Path $env:LOCALAPPDATA "Programs\Python\clawd"
$ClawdBin = Join-Path $BinDir "clawd.cmd"
$ClawdOrigBin = Join-Path $BinDir "clawd.orig.cmd"
$RepoUrl = "https://github.com/your-org/claw-code-tingfeng"
$PythonMinVersion = "3.10"
# ClawGod-inspired: environment variable injection for privacy/disabled checks
$DisableTelemetry = $true
$DisableInstallChecks = $true

function Check-Prerequisites {
    Write-Info "检查前置条件..."

    # 检查 Python
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        $python = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if (-not $python) {
        Write-Error "未找到 Python，请先安装 Python >= $PythonMinVersion"
        exit 1
    }

    $pythonVersion = & $python.Source --version 2>&1
    Write-Ok "Python 版本: $pythonVersion"

    # 创建安装目录
    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }
    if (-not (Test-Path $BinDir)) {
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    }
}

function Create-VirtualEnv {
    Write-Info "创建 Python 虚拟环境..."

    if (Test-Path $VenvDir) {
        Write-Warn "虚拟环境已存在，跳过创建"
        return
    }

    & python -m venv $VenvDir
    Write-Ok "虚拟环境创建成功: $VenvDir"
}

function Install-Dependencies {
    Write-Info "安装 Clawd Code 及依赖..."

    $pipPath = Join-Path $VenvDir "Scripts\pip.exe"
    $pythonPath = Join-Path $VenvDir "Scripts\python.exe"

    if (Test-Path "pyproject.toml") {
        Write-Info "从本地源码安装..."
        & $pipPath install -e .
    } else {
        Write-Info "从 PyPI 安装..."
        & $pipPath install clawd-code 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "PyPI 包未找到，尝试从 GitHub 安装..."
            & $pipPath install git+$RepoUrl.git 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Error "安装失败，请手动安装"
                exit 1
            }
        }
    }

    Write-Ok "依赖安装完成"
}

function Create-Launcher {
    Write-Info "创建启动脚本..."

    # 备份原版
    if ((Test-Path $ClawdBin) -and (-not (Test-Path $ClawdOrigBin))) {
        Copy-Item $ClawdBin $ClawdOrigBin
        Write-Ok "原版已备份到 $ClawdOrigBin"
    }

    # 创建 launcher
    $launcherContent = @"
@echo off
REM Clawd Code Launcher
REM 自动激活虚拟环境并启动
REM Inspired by ClawGod's cli.js wrapper pattern

set VENV_DIR=$VenvDir
set INSTALL_DIR=$InstallDir

REM 激活虚拟环境
call "%VENV_DIR%\Scripts\activate.bat"

REM ClawGod-inspired: 注入环境变量
if exist "%INSTALL_DIR%\.env" (
    for /f "tokens=1,* delims==" %%a in ('type "%INSTALL_DIR%\.env" ^| findstr /v "^#"') do (
        set %%a=%%b
    )
)

REM ClawGod-inspired: 禁用遥测和非必要网络流量
if not defined CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC (
    set CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
)

REM ClawGod-inspired: 跳过安装检查
if not defined DISABLE_INSTALLATION_CHECKS (
    set DISABLE_INSTALLATION_CHECKS=1
)

REM 启动 Clawd Code
python -m src.main %*
"@

    Set-Content -Path $ClawdBin -Value $launcherContent -Encoding ASCII
    Write-Ok "启动脚本已创建: $ClawdBin"
}

function Create-DefaultConfig {
    Write-Info "创建默认配置..."

    # .env 配置
    $envFile = Join-Path $InstallDir ".env"
    if (-not (Test-Path $envFile)) {
        $envContent = @"
# Clawd Code 配置文件
# 请填入你的 API 密钥

# OpenAI
CLAWD_LLM_PROVIDER=openai
CLAWD_LLM_API_KEY=sk-your-openai-key-here
CLAWD_LLM_MODEL=gpt-4

# Anthropic (取消注释以使用)
# CLAWD_LLM_PROVIDER=anthropic
# CLAWD_LLM_API_KEY=sk-ant-your-anthropic-key-here
# CLAWD_LLM_MODEL=claude-3-5-sonnet

# 自定义 API 端点
# CLAWD_LLM_BASE_URL=https://api.your-proxy.com

# 其他配置
# CLAWD_FEATURE_GOD_MODE=false
# CLAWD_FEATURE_DEBUG_TRACING=false
"@
        Set-Content -Path $envFile -Value $envContent -Encoding UTF8
        Write-Ok "默认 .env 已创建: $envFile"
    }

    # features.json
    $featuresFile = Join-Path $InstallDir "features.json"
    if (-not (Test-Path $featuresFile)) {
        $featuresContent = @"
{
  "god_mode": false,
  "ultraplan": true,
  "agent_teams": true,
  "no_safety_check": false,
  "internal_commands": true,
  "debug_tracing": false,
  "tengu_harbor": true,
  "tengu_session_memory": true,
  "enable_output_compression": true
}
"@
        Set-Content -Path $featuresFile -Value $featuresContent -Encoding UTF8
        Write-Ok "默认 features.json 已创建"
    }

    # provider.json (ClawGod 风格)
    $providerFile = Join-Path $InstallDir "provider.json"
    if (-not (Test-Path $providerFile)) {
        $providerContent = @"
{
  "apiKey": "",
  "baseURL": "https://api.anthropic.com",
  "model": "",
  "smallModel": "",
  "timeoutMs": 300000,
  "providers": {
    "openai": {
      "apiKey": "",
      "baseURL": "https://api.openai.com",
      "model": "gpt-4",
      "smallModel": "gpt-3.5-turbo",
      "timeoutMs": 300000
    },
    "anthropic": {
      "apiKey": "",
      "baseURL": "https://api.anthropic.com",
      "model": "claude-3-5-sonnet",
      "smallModel": "claude-3-haiku",
      "timeoutMs": 300000
    }
  }
}
"@
        Set-Content -Path $providerFile -Value $providerContent -Encoding UTF8
        Write-Ok "默认 provider.json 已创建"
    }
}

function Setup-PathIntegration {
    Write-Info "配置 PATH 集成..."

    # 添加到用户 PATH
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -notlike "*$BinDir*") {
        $newPath = "$currentPath;$BinDir"
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Ok "已添加到用户 PATH: $BinDir"
    }

    # 刷新当前会话 PATH
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Write-PostInstall {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║   🦞  Clawd Code 安装成功！              ║" -ForegroundColor Green
    Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "📍 安装目录: $InstallDir"
    Write-Host "📍 虚拟环境: $VenvDir"
    Write-Host "📍 启动命令: clawd"
    Write-Host ""
    Write-Host "🔧 下一步:"
    Write-Host "   1. 编辑 $InstallDir\.env 填入 API 密钥"
    Write-Host "   2. 运行: clawd --help"
    Write-Host "   3. 启动: clawd"
    Write-Host ""
    Write-Host "💡 提示:"
    Write-Host "   - 原版备份在: $ClawdOrigBin"
    Write-Host "   - 卸载: powershell -File install.ps1 -Uninstall"
    Write-Host "   - 恢复原版: powershell -File install.ps1 -Revert"
    Write-Host "   - 查看状态: powershell -File install.ps1 -Status"
    Write-Host ""
}

function Verify-Installation {
    """ClawGod-inspired: 安装后验证步骤"""
    Write-Info "验证安装..."

    $verified = 0

    # 验证虚拟环境
    $pythonPath = Join-Path $VenvDir "Scripts\python.exe"
    if (Test-Path $pythonPath) {
        $ver = & $pythonPath --version 2>&1
        Write-Ok "Python: $ver"
        $verified++
    } else {
        Write-Warn "Python 可执行文件未找到"
    }

    # 验证 clawd 模块
    $pipPath = Join-Path $VenvDir "Scripts\pip.exe"
    if (Test-Path $pipPath) {
        $modules = & $pipPath list 2>&1 | Select-String -Pattern "clawd|openai|anthropic"
        if ($modules) {
            foreach ($mod in $modules) {
                Write-Ok "已安装: $($mod.ToString().Trim())"
                $verified++
            }
        } else {
            Write-Warn "未找到已安装的 clawd 相关包"
        }
    }

    # 验证配置文件
    @(".env", "features.json", "provider.json") | ForEach-Object {
        $cfgFile = Join-Path $InstallDir $_
        if (Test-Path $cfgFile) {
            Write-Ok "配置: $_"
            $verified++
        } else {
            Write-Warn "配置缺失: $_"
        }
    }

    # 验证 launcher
    if (Test-Path $ClawdBin) {
        Write-Ok "启动脚本: $ClawdBin"
        $verified++
    }

    Write-Host ""
    Write-Host "───────────────────────────────────────────────"
    Write-Host "  验证完成: $verified 项通过"
    Write-Host "───────────────────────────────────────────────"
    Write-Host ""

    return $verified
}

function Show-Status {
    """显示 Clawd Code 安装状态（借鉴 ClawGod 的 --verify 模式）"""
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════╗"
    Write-Host "║   🦞  Clawd Code 状态报告               ║"
    Write-Host "╚══════════════════════════════════════════╝"
    Write-Host ""

    # 检查安装状态
    if (Test-Path $ClawdBin) {
        Write-Ok "启动脚本: $ClawdBin"
        $content = Get-Content $ClawdBin -Raw
        if ($content -match "clawd") {
            Write-Ok "版本: 增强版 (ClawGod-inspired)"
        } else {
            Write-Host "  $([char]0x25CB) 版本: 原版" -ForegroundColor DarkGray
        }
    } else {
        Write-Error "启动脚本: 未安装"
    }

    # 检查虚拟环境
    if (Test-Path $VenvDir) {
        Write-Ok "虚拟环境: $VenvDir"
    } else {
        Write-Error "虚拟环境: 不存在"
    }

    # 检查备份
    if (Test-Path $ClawdOrigBin) {
        Write-Ok "原版备份: $ClawdOrigBin"
    } else {
        Write-Host "  $([char]0x25CB) 原版备份: 无" -ForegroundColor DarkGray
    }

    # 检查配置
    @(".env", "features.json", "provider.json") | ForEach-Object {
        $cfgFile = Join-Path $InstallDir $_
        if (Test-Path $cfgFile) {
            Write-Ok "配置: $_"
        } else {
            Write-Host "  $([char]0x25CB) 配置: $_ (未创建)" -ForegroundColor DarkGray
        }
    }

    Write-Host ""
    Write-Host "───────────────────────────────────────────────"
    Write-Host "  命令:"
    Write-Host "    clawd          — 启动 Clawd Code"
    Write-Host "    clawd.orig     — 启动原版（如有备份）"
    Write-Host "    -Uninstall     — 卸载"
    Write-Host "    -Revert        — 恢复原版"
    Write-Host "    -Status        — 显示此报告"
    Write-Host "───────────────────────────────────────────────"
    Write-Host ""
}

function Uninstall {
    Write-Info "开始卸载..."

    $removed = 0

    if (Test-Path $ClawdBin) {
        Remove-Item $ClawdBin -Force
        Write-Ok "已删除 $ClawdBin"
        $removed++
    }

    if (Test-Path $VenvDir) {
        Remove-Item $VenvDir -Recurse -Force
        Write-Ok "已删除虚拟环境"
        $removed++
    }

    if (Test-Path $InstallDir) {
        Write-Warn "配置目录 $InstallDir 已保留"
        Write-Warn "如需完全删除，请手动删除: $InstallDir"
    }

    Write-Host ""
    Write-Host "───────────────────────────────────────────────"
    Write-Host "  卸载完成: $removed 项已删除"
    Write-Host "  配置文件已保留（可重新安装恢复）"
    Write-Host "───────────────────────────────────────────────"
    Write-Host ""
}

function Revert-Original {
    Write-Info "恢复到原版..."

    if (-not (Test-Path $ClawdOrigBin)) {
        Write-Error "未找到原版备份: $ClawdOrigBin"
        exit 1
    }

    Move-Item $ClawdOrigBin $ClawdBin -Force
    Write-Ok "已恢复到原版"
}

# ===== 主流程 =====
function Main {
    if ($Uninstall) {
        Uninstall
        exit 0
    }

    if ($Revert) {
        Revert-Original
        exit 0
    }

    if ($Status) {
        Show-Status
        exit 0
    }

    Write-Host ""
    Write-Host "╔══════════════════════════════════════════╗"
    Write-Host "║   🦞  Clawd Code 一键安装脚本           ║"
    Write-Host "║   Inspired by Project B (ClawGod)       ║"
    Write-Host "╚══════════════════════════════════════════╝"
    Write-Host ""

    Check-Prerequisites
    Create-VirtualEnv
    Install-Dependencies
    Create-Launcher
    Create-DefaultConfig
    Setup-PathIntegration
    Verify-Installation
    Write-PostInstall
}

Main
