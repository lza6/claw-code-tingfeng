chcp 65001 >nul 2>&1
@echo off
REM 从 pyproject.toml 动态读取版本号
for /f "tokens=2 delims==" %%a in ('findstr /r "^version" pyproject.toml') do (
    set VERSION_RAW=%%a
)
set VERSION=%VERSION_RAW:"=%
set VERSION=%VERSION: =%

echo ========================================
echo   Clawd Code - AI 编程代理框架 v%VERSION%
echo ========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [信息] Python 版本:
python --version
echo.

REM 检查并创建虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo [信息] 正在创建虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
    echo [成功] 虚拟环境已创建
) else (
    echo [信息] 虚拟环境已存在
)
echo.

REM 激活虚拟环境
echo [信息] 激活虚拟环境...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [警告] 虚拟环境激活失败，继续使用系统 Python
)
echo.

REM 检查并安装依赖
pip show openai >nul 2>&1
if errorlevel 1 (
    echo [信息] 正在安装依赖包...
    if exist "requirements.txt" (
        pip install -r requirements.txt
    ) else (
        echo [信息] 未找到 requirements.txt，安装核心依赖...
        pip install openai anthropic
    )
    echo [成功] 依赖安装完成
) else (
    echo [信息] 依赖已安装
)
echo.

REM 检查并自动创建 .env 文件
if not exist ".env" (
    echo [警告] 未找到 .env 配置文件，正在从 .env.example 创建...
    copy .env.example .env >nul 2>&1
    if errorlevel 1 (
        echo [错误] .env 文件创建失败，请手动复制 .env.example 为 .env
    ) else (
        echo [成功] 已自动创建 .env 文件，请编辑并配置你的 API key
    )
    echo.
)

REM 安全检查：检查 .env 是否被 Git 跟踪
git ls-files --error-unmatch .env >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [严重警告] .env 文件已被 Git 跟踪！
    echo   这可能导致您的 API 密钥被公开泄露！
    echo   请立即执行以下命令：
    echo     git rm --cached .env
    echo     echo .env >> .gitignore
    echo.
)

REM 安全检查：扫描 .env 文件中的密钥模式
if exist ".env" (
    findstr /i "sk-" .env >nul 2>&1
    if not errorlevel 1 (
        findstr /i "sk-or-v1" .env >nul 2>&1
        if errorlevel 1 (
            echo [安全提示] .env 文件中包含可能的 API 密钥 (sk-)
            echo   请确保 .env 已加入 .gitignore，且未提交到远程仓库
            echo.
        )
    )
    findstr /i "ghp_" .env >nul 2>&1
    if not errorlevel 1 (
        echo [安全提示] .env 文件中包含可能的 GitHub Token (ghp_)
        echo   请确保 .env 已加入 .gitignore，且未提交到远程仓库
        echo.
    )
    findstr /i "AKIA" .env >nul 2>&1
    if not errorlevel 1 (
        echo [安全提示] .env 文件中包含可能的 AWS Access Key (AKIA)
        echo   请确保 .env 已加入 .gitignore，且未提交到远程仓库
        echo.
    )
)

REM 解析命令行参数
set MODE=%1
set UPGRADE=
if /i "%MODE%"=="upgrade" (
    set UPGRADE=1
    set MODE=cli
) else if /i "%MODE%"=="cli" (
    echo %2 | findstr /i "--upgrade" >nul
    if not errorlevel 1 set UPGRADE=1
) else if "%MODE%"=="" (
    set MODE=cli
)

REM 如果请求升级，强制重新安装依赖
if "%UPGRADE%"=="1" (
    echo [信息] 正在升级依赖包...
    if exist "requirements.txt" (
        pip install --upgrade -r requirements.txt
    ) else (
        pip install --upgrade openai anthropic
    )
    echo [成功] 依赖升级完成
    echo.
)

if /i "%MODE%"=="cli" (
    REM 启动交互式 REPL 模式（类 Claude Code）
    echo ========================================
    echo   启动 Clawd Code 交互式 AI 编程代理
    echo ========================================
    echo.
    python -m src.main
) else if /i "%MODE%"=="doctor" (
    REM 运行环境诊断
    python -m src.main doctor
) else (
    REM 默认启动交互式 REPL
    echo ========================================
    echo   启动 Clawd Code CLI v%VERSION%
    echo ========================================
    echo.
    python -m src.main
)

echo.
echo ========================================
echo   完成
echo ========================================
pause
