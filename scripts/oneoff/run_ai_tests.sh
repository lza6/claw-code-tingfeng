#!/bin/bash
# AI能力测试快速启动脚本 (Linux/Mac)

echo "================================================================================"
echo "🚀 Clawd Code AI能力测试启动器"
echo "================================================================================"
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到Python3,请先安装Python 3.10+"
    exit 1
fi

echo "✅ Python已安装: $(python3 --version)"
echo ""

# 检查依赖
echo "📦 检查依赖..."
if ! python3 -c "import httpx" 2>/dev/null; then
    echo "⚠️  正在安装依赖..."
    pip3 install httpx
else
    echo "✅ 依赖已安装"
fi

echo ""
echo "================================================================================"
echo "准备启动AI能力测试..."
echo "================================================================================"
echo ""
echo "测试项目:"
echo "  1. 基础对话能力"
echo "  2. 贪吃蛇游戏生成"
echo "  3. 天气预报页面生成"
echo "  4. 多轮对话能力"
echo "  5. 上下文压缩"
echo "  6. 工具调用模拟"
echo "  7. 响应质量评估"
echo ""
echo "预计耗时: 5-10分钟"
echo ""

read -p "按回车键继续..."

echo ""
echo "🚀 开始测试..."
echo ""

cd tests/ai_evaluation
python3 run_test.py

echo ""
echo "================================================================================"
echo "测试完成!"
echo "================================================================================"
echo ""
echo "查看结果:"
echo "  - 测试输出: tests/ai_evaluation/tests/test_outputs/"
echo "  - 日志文件: logs/"
echo ""
