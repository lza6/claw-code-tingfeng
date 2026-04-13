#!/usr/bin/env bash
# Clawd Code - AI 编程代理框架
# Mac/Linux 一键启动脚本

set -e

# 从 pyproject.toml 动态读取版本号
VERSION=$(grep -E '^version\s*=' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')

echo "========================================"
echo "  Clawd Code - AI 编程代理框架 v${VERSION}"
echo "========================================"
echo ""

# 检查 Python 是否安装
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3，请先安装 Python 3.10+"
    echo "Mac: brew install python3"
    echo "Ubuntu/Debian: sudo apt install python3"
    echo "CentOS/RHEL: sudo yum install python3"
    exit 1
fi

echo "[信息] Python 版本:"
python3 --version
echo ""

# 检查并创建虚拟环境
if [ ! -d "venv" ]; then
    echo "[信息] 正在创建虚拟环境..."
    python3 -m venv venv
    echo "[成功] 虚拟环境已创建"
else
    echo "[信息] 虚拟环境已存在"
fi
echo ""

# 激活虚拟环境
echo "[信息] 激活虚拟环境..."
source venv/bin/activate
echo ""

# 检查并安装依赖
if ! pip show openai >/dev/null 2>&1; then
    echo "[信息] 正在安装依赖包..."
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    else
        echo "[信息] 未找到 requirements.txt，安装核心依赖..."
        pip install openai anthropic PySide6
    fi
    echo "[成功] 依赖安装完成"
else
    echo "[信息] 依赖已安装"
fi
echo ""

# 检查并自动创建 .env 文件
if [ ! -f ".env" ]; then
    echo "[警告] 未找到 .env 配置文件，正在从 .env.example 创建..."
    if cp .env.example .env 2>/dev/null; then
        echo "[成功] 已自动创建 .env 文件，请编辑并配置你的 API key"
    else
        echo "[错误] .env 文件创建失败，请手动复制 .env.example 为 .env"
    fi
    echo ""
fi

# 安全检查：检查 .env 是否被 Git 跟踪
if command -v git &> /dev/null; then
    if git ls-files --error-unmatch .env &>/dev/null; then
        echo ""
        echo "[严重警告] .env 文件已被 Git 跟踪！"
        echo "  这可能导致您的 API 密钥被公开泄露！"
        echo "  请立即执行以下命令："
        echo "    git rm --cached .env"
        echo "    echo .env >> .gitignore"
        echo ""
    fi
fi

# 安全检查：扫描 .env 文件中的密钥模式
if [ -f ".env" ]; then
    if grep -qi "sk-" .env 2>/dev/null && ! grep -qi "sk-or-v1" .env 2>/dev/null; then
        echo "[安全提示] .env 文件中包含可能的 API 密钥 (sk-)"
        echo "  请确保 .env 已加入 .gitignore，且未提交到远程仓库"
        echo ""
    fi
    if grep -qi "ghp_" .env 2>/dev/null; then
        echo "[安全提示] .env 文件中包含可能的 GitHub Token (ghp_)"
        echo "  请确保 .env 已加入 .gitignore，且未提交到远程仓库"
        echo ""
    fi
    if grep -qi "AKIA" .env 2>/dev/null; then
        echo "[安全提示] .env 文件中包含可能的 AWS Access Key (AKIA)"
        echo "  请确保 .env 已加入 .gitignore，且未提交到远程仓库"
        echo ""
    fi
fi

# 解析命令行参数
MODE="${1:-cli}"
UPGRADE=""

# 检查是否有 --upgrade 参数
if [ "$MODE" = "upgrade" ] || [ "$MODE" = "--upgrade" ] || [ "$2" = "--upgrade" ]; then
    UPGRADE="1"
fi

# 如果请求升级，强制重新安装依赖
if [ "$UPGRADE" = "1" ]; then
    echo "[信息] 正在升级依赖包..."
    if [ -f "requirements.txt" ]; then
        pip install --upgrade -r requirements.txt
    else
        pip install --upgrade openai anthropic PySide6
    fi
    echo "[成功] 依赖升级完成"
    echo ""
fi

# 规范化模式（去除 --upgrade 参数）
BASE_MODE="${MODE}"
if [ "$BASE_MODE" = "upgrade" ] || [ "$BASE_MODE" = "--upgrade" ]; then
    BASE_MODE="cli"
fi

if [ "$BASE_MODE" = "cli" ] || [ "$BASE_MODE" = "--cli" ] || [ "$BASE_MODE" = "-c" ]; then
    # 启动 CLI 模式
    echo "========================================"
    echo "  可用命令"
    echo "========================================"
    echo ""
    echo "  python -m src.main summary        - 查看移植工作区摘要"
    echo "  python -m src.main manifest       - 查看工作区清单"
    echo "  python -m src.main commands       - 列出命令条目"
    echo "  python -m src.main tools          - 列出工具条目"
    echo "  python -m src.main parity-audit   - 运行奇偶校验审计"
    echo "  python -m src.main setup-report   - 查看设置报告"
    echo "  python -m src.main --help         - 查看所有可用命令"
    echo ""
    echo "========================================"
    echo "  快速开始"
    echo "========================================"
    echo ""
    python -m src.main summary
else
    # 默认启动 CLI
    echo "========================================"
    echo "  启动 Clawd Code CLI v${VERSION}"
    echo "========================================"
    echo ""
    python -m src.main summary
fi

echo ""
echo "========================================"
echo "  完成"
echo "========================================"
