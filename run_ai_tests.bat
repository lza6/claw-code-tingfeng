@echo off
REM AI能力测试快速启动脚本 (Windows)
echo ================================================================================
echo 🚀 Clawd Code AI能力测试启动器
echo ================================================================================
echo.

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到Python,请先安装Python 3.10+
    pause
    exit /b 1
)

echo ✅ Python已安装
echo.

REM 检查依赖
echo 📦 检查依赖...
python -c "import httpx" >nul 2>&1
if errorlevel 1 (
    echo ⚠️  正在安装依赖...
    pip install httpx
) else (
    echo ✅ 依赖已安装
)

echo.
echo ================================================================================
echo 准备启动AI能力测试...
echo ================================================================================
echo.
echo 测试项目:
echo   1. 基础对话能力
echo   2. 贪吃蛇游戏生成
echo   3. 天气预报页面生成
echo   4. 多轮对话能力
echo   5. 上下文压缩
echo   6. 工具调用模拟
echo   7. 响应质量评估
echo.
echo 预计耗时: 5-10分钟
echo.

pause

echo.
echo 🚀 开始测试...
echo.

cd tests\ai_evaluation
python run_test.py

echo.
echo ================================================================================
echo 测试完成!
echo ================================================================================
echo.
echo 查看结果:
echo   - 测试输出: tests\ai_evaluation\tests\test_outputs\
echo   - 日志文件: logs\
echo.

pause
