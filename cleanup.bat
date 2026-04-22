@echo off
REM 清理 claw-code-tingfeng 项目的临时文件和缓存

echo ========================================
echo 清理项目临时文件
echo ========================================
echo.

REM 删除 Python 缓存
echo [1/5] 删除 Python __pycache__...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"

REM 删除 pytest 缓存
echo [2/5] 删除 pytest 缓存...
if exist .pytest_cache rd /s /q .pytest_cache

REM 删除 coverage 报告
echo [3/5] 删除 coverage 报告...
if exist htmlcov rd /s /q htmlcov
if exist .coverage del /q .coverage

REM 删除临时文件
echo [4/5] 删除临时文件...
del /q /s *.pyc 2>nul
del /q /s *.pyo 2>nul
del /q /s *~ 2>nul

REM 检查 git 状态
echo [5/5] Git 状态检查...
git status --short

echo.
echo ========================================
echo 清理完成!
echo ========================================
