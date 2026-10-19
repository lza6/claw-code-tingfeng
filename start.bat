chcp 65001 >nul 2>&1
@echo off
REM Read version from pyproject.toml dynamically
for /f "tokens=2 delims==" %%a in ('findstr /r "^version" pyproject.toml') do (
    set VERSION_RAW=%%a
)
set VERSION=%VERSION_RAW:"=%
set VERSION=%VERSION: =%

echo ========================================
echo   Clawd Code - AI Coding Agent Framework v%VERSION%
echo ========================================
echo.

REM Resolve Python: prefer 3.10 (verified), then py -3 / python
set "PYTHON="
py -3.10 --version >nul 2>&1
if not errorlevel 1 set "PYTHON=py -3.10"
if not defined PYTHON (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [INFO] Python version:
%PYTHON% --version
echo.

REM Check and create virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
) else (
    echo [INFO] Virtual environment already exists
)
echo.

REM Activate virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [WARN] Activation failed; using system Python
) else (
    set "PYTHON=venv\Scripts\python.exe"
)
echo.

REM Check and install dependencies
pip show openai >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    pip install --timeout 120 --retries 5 --upgrade setuptools wheel
    if errorlevel 1 echo [WARN] Failed to install build tools; continuing
    if exist "pyproject.toml" (
        pip install --timeout 120 --retries 5 --no-build-isolation -e .
    ) else (
        if exist "requirements.txt" (
            pip install --timeout 120 --retries 5 -r requirements.txt
        ) else (
            echo [INFO] requirements.txt not found; installing core deps...
            pip install --timeout 120 --retries 5 openai anthropic
        )
    )
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed; check network and requirements.txt
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed
) else (
    echo [INFO] Dependencies already installed
)
echo.

REM Check and create .env
if not exist ".env" (
    echo [WARN] .env not found; creating from .env.example...
    copy .env.example .env >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to create .env; copy .env.example to .env manually
    ) else (
        echo [OK] Created .env; edit it and set your API key
    )
    echo.
)

REM Security: check whether .env is tracked by Git
git ls-files --error-unmatch .env >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [CRITICAL] .env is tracked by Git!
    echo   This may expose your API keys publicly!
    echo   Run the following commands:
    echo     git rm --cached .env
    echo     echo .env >> .gitignore
    echo.
)

REM Security: scan .env for key patterns
if exist ".env" (
    findstr /i "sk-" .env >nul 2>&1
    if not errorlevel 1 (
        findstr /i "sk-or-v1" .env >nul 2>&1
        if errorlevel 1 (
            echo [SECURITY] .env contains a possible API key (sk-)
            echo   Ensure .env is in .gitignore and not committed
            echo.
        )
    )
    findstr /i "ghp_" .env >nul 2>&1
    if not errorlevel 1 (
        echo [SECURITY] .env contains a possible GitHub token (ghp_)
        echo   Ensure .env is in .gitignore and not committed
        echo.
    )
    findstr /i "AKIA" .env >nul 2>&1
    if not errorlevel 1 (
        echo [SECURITY] .env contains a possible AWS access key (AKIA)
        echo   Ensure .env is in .gitignore and not committed
        echo.
    )
)

REM Parse command line arguments
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

REM Force reinstall when upgrade requested
if "%UPGRADE%"=="1" (
    echo [INFO] Upgrading dependencies...
    pip install --timeout 120 --retries 5 --upgrade setuptools wheel
    if errorlevel 1 echo [WARN] Failed to install build tools; continuing
    if exist "pyproject.toml" (
        pip install --timeout 120 --retries 5 --no-build-isolation --upgrade -e .
    ) else (
        if exist "requirements.txt" (
            pip install --timeout 120 --retries 5 --upgrade -r requirements.txt
        ) else (
            pip install --timeout 120 --retries 5 --upgrade openai anthropic
        )
    )
    if errorlevel 1 (
        echo [ERROR] Dependency upgrade failed; check network and requirements.txt
        pause
        exit /b 1
    )
    echo [OK] Dependencies upgraded
    echo.
)

if /i "%MODE%"=="cli" (
    REM Launch interactive REPL (Claude Code style)
    echo ========================================
    echo   Starting Clawd Code interactive AI coding agent
    echo ========================================
    echo.
    %PYTHON% -m src chat
) else if /i "%MODE%"=="doctor" (
    REM Run environment diagnostics
    %PYTHON% -m src doctor
) else (
    REM Default: interactive REPL
    echo ========================================
    echo   Starting Clawd Code CLI v%VERSION%
    echo ========================================
    echo.
    %PYTHON% -m src chat
)

echo.
echo ========================================
echo   Done
echo ========================================
pause
