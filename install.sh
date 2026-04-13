#!/bin/bash
# Clawd Code — 一键安装脚本 (macOS/Linux)
# Inspired by Project B (ClawGod)'s install.sh
# Usage: curl -fsSL https://... | bash
#    or: bash install.sh [--uninstall|--revert|--version X.Y.Z]

set -e

# ===== 颜色定义 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ===== 配置 =====
PROJECT_NAME="Clawd Code"
INSTALL_DIR="$HOME/.clawd"
VENV_DIR="$HOME/.clawd/venv"
BIN_DIR="$HOME/.local/bin"
CLAWD_BIN="$BIN_DIR/clawd"
CLAWD_ORIG_BIN="$BIN_DIR/clawd.orig"
REPO_URL="https://github.com/your-org/claw-code-tingfeng"
PYTHON_MIN_VERSION="3.10"

# ===== 工具函数 =====
log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_prerequisites() {
    log_info "检查前置条件..."

    # 检查 Python
    if ! command -v python3 &>/dev/null; then
        log_error "未找到 Python3，请先安装 Python >= ${PYTHON_MIN_VERSION}"
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log_ok "Python 版本: ${PYTHON_VERSION}"

    # 检查 pip
    if ! command -v pip3 &>/dev/null && ! python3 -m pip --version &>/dev/null; then
        log_error "未找到 pip，请先安装 pip"
        exit 1
    fi

    # 检查 git (可选，用于从仓库安装)
    if command -v git &>/dev/null; then
        log_ok "git 已安装"
    else
        log_warn "git 未安装，将使用 pip 安装"
    fi

    # 创建安装目录
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$BIN_DIR"
}

create_virtualenv() {
    log_info "创建 Python 虚拟环境..."

    if [ -d "$VENV_DIR" ]; then
        log_warn "虚拟环境已存在，跳过创建"
        return
    fi

    python3 -m venv "$VENV_DIR"
    log_ok "虚拟环境创建成功: ${VENV_DIR}"
}

install_dependencies() {
    log_info "安装 Clawd Code 及依赖..."

    # 激活虚拟环境
    source "$VENV_DIR/bin/activate"

    # 从当前目录或 pip 安装
    if [ -f "pyproject.toml" ]; then
        log_info "从本地源码安装..."
        pip install -e .
    else
        log_info "从 PyPI 安装..."
        pip install clawd-code 2>/dev/null || {
            log_warn "PyPI 包未找到，尝试从 GitHub 安装..."
            pip install git+${REPO_URL}.git 2>/dev/null || {
                log_error "安装失败，请手动安装"
                exit 1
            }
        }
    fi

    log_ok "依赖安装完成"
}

create_launcher() {
    log_info "创建启动脚本..."

    # 备份原版
    if [ -f "$CLAWD_BIN" ] && [ ! -f "$CLAWD_ORIG_BIN" ]; then
        cp "$CLAWD_BIN" "$CLAWD_ORIG_BIN"
        log_ok "原版已备份到 ${CLAWD_ORIG_BIN}"
    fi

    # 创建 launcher
    cat > "$CLAWD_BIN" << LAUNCHER
#!/bin/bash
# Clawd Code Launcher
# 自动激活虚拟环境并启动

VENV_DIR="${VENV_DIR}"
INSTALL_DIR="${INSTALL_DIR}"

# 激活虚拟环境
if [ -f "\$VENV_DIR/bin/activate" ]; then
    source "\$VENV_DIR/bin/activate"
fi

# 注入环境变量
if [ -f "\$INSTALL_DIR/.env" ]; then
    set -a
    source "\$INSTALL_DIR/.env"
    set +a
fi

# 启动 Clawd Code
exec python3 -m src.main "\$@"
LAUNCHER

    chmod +x "$CLAWD_BIN"
    log_ok "启动脚本已创建: ${CLAWD_BIN}"
}

create_default_config() {
    log_info "创建默认配置..."

    # .env 配置
    if [ ! -f "$INSTALL_DIR/.env" ]; then
        cat > "$INSTALL_DIR/.env" << 'ENVFILE'
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
ENVFILE
        chmod 600 "$INSTALL_DIR/.env"
        log_ok "默认 .env 已创建: ${INSTALL_DIR}/.env"
    fi

    # features.json
    if [ ! -f "$INSTALL_DIR/features.json" ]; then
        cat > "$INSTALL_DIR/features.json" << 'FEATURES'
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
FEATURES
        log_ok "默认 features.json 已创建"
    fi

    # provider.json (ClawGod 风格)
    if [ ! -f "$INSTALL_DIR/provider.json" ]; then
        cat > "$INSTALL_DIR/provider.json" << 'PROVIDER'
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
PROVIDER
        log_ok "默认 provider.json 已创建"
    fi
}

setup_shell_integration() {
    log_info "配置 Shell 集成..."

    # 添加到 PATH (如果不存在)
    if ! echo "$PATH" | grep -q "$BIN_DIR"; then
        SHELL_RC=""
        if [ -f "$HOME/.bashrc" ]; then
            SHELL_RC="$HOME/.bashrc"
        elif [ -f "$HOME/.zshrc" ]; then
            SHELL_RC="$HOME/.zshrc"
        elif [ -f "$HOME/.bash_profile" ]; then
            SHELL_RC="$HOME/.bash_profile"
        fi

        if [ -n "$SHELL_RC" ]; then
            echo "" >> "$SHELL_RC"
            echo "# Clawd Code" >> "$SHELL_RC"
            echo "export PATH=\"${BIN_DIR}:\$PATH\"" >> "$SHELL_RC"
            log_ok "已添加到 ${SHELL_RC}"
        fi
    fi

    # 刷新 hash
    hash -r 2>/dev/null || true
}

print_post_install() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${NC}  ${PROJECT_NAME} 安装成功！          ${GREEN}║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo "📍 安装目录: ${INSTALL_DIR}"
    echo "📍 虚拟环境: ${VENV_DIR}"
    echo "📍 启动命令: ${CLAWD_BIN}"
    echo ""
    echo "🔧 下一步:"
    echo "   1. 编辑 ${INSTALL_DIR}/.env 填入 API 密钥"
    echo "   2. 运行: clawd --help"
    echo "   3. 启动: clawd"
    echo ""
    echo "💡 提示:"
    echo "   - 原版备份在: ${CLAWD_ORIG_BIN}"
    echo "   - 卸载: bash install.sh --uninstall"
    echo "   - 恢复原版: bash install.sh --revert"
    echo ""
}

show_status() {
    """显示 Clawd Code 安装状态（借鉴 ClawGod 的 --verify 模式）"""
    echo ""
    echo "╔══════════════════════════════════════════╗"
    echo "║   🦞  Clawd Code 状态报告               ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""

    # 检查安装状态
    if [ -f "$CLAWD_BIN" ]; then
        echo -e "  ${GREEN}✓${NC} 启动脚本: ${CLAWD_BIN}"
        if grep -q "clawd" "$CLAWD_BIN" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} 版本: 增强版 (ClawGod-inspired)"
        else
            echo -e "  ${DIM}✓${NC} 版本: 原版"
        fi
    else
        echo -e "  ${RED}✗${NC} 启动脚本: 未安装"
    fi

    # 检查虚拟环境
    if [ -d "$VENV_DIR" ]; then
        echo -e "  ${GREEN}✓${NC} 虚拟环境: ${VENV_DIR}"
    else
        echo -e "  ${RED}✗${NC} 虚拟环境: 不存在"
    fi

    # 检查备份
    if [ -f "$CLAWD_ORIG_BIN" ]; then
        echo -e "  ${GREEN}✓${NC} 原版备份: ${CLAWD_ORIG_BIN}"
    else
        echo -e "  ${DIM}○${NC} 原版备份: 无"
    fi

    # 检查配置
    for cfg in ".env" "features.json" "provider.json"; do
        if [ -f "$INSTALL_DIR/$cfg" ]; then
            echo -e "  ${GREEN}✓${NC} 配置: $cfg"
        else
            echo -e "  ${DIM}○${NC} 配置: $cfg (未创建)"
        fi
    done

    echo ""
    echo "───────────────────────────────────────────────"
    echo "  命令:"
    echo "    clawd          — 启动 Clawd Code"
    echo "    clawd.orig     — 启动原版（如有备份）"
    echo "    --uninstall    — 卸载"
    echo "    --revert       — 恢复原版"
    echo "    --status       — 显示此报告"
    echo "───────────────────────────────────────────────"
    echo ""
}

uninstall() {
    log_info "开始卸载..."

    local removed=0

    # 删除启动脚本
    if [ -f "$CLAWD_BIN" ]; then
        rm "$CLAWD_BIN"
        log_ok "已删除 ${CLAWD_BIN}"
        ((removed++))
    fi

    # 删除虚拟环境
    if [ -d "$VENV_DIR" ]; then
        rm -rf "$VENV_DIR"
        log_ok "已删除虚拟环境"
        ((removed++))
    fi

    # 保留配置目录
    if [ -d "$INSTALL_DIR" ]; then
        log_warn "配置目录 ${INSTALL_DIR} 已保留"
        log_warn "如需完全删除，请手动运行: rm -rf ${INSTALL_DIR}"
    fi

    # 刷新 shell 缓存（借鉴 ClawGod）
    hash -r 2>/dev/null

    echo ""
    echo "───────────────────────────────────────────────"
    echo "  卸载完成: ${removed} 项已删除"
    echo "  配置文件已保留（可重新安装恢复）"
    echo "───────────────────────────────────────────────"
    echo ""
}

revert_to_original() {
    log_info "恢复到原版..."

    if [ ! -f "$CLAWD_ORIG_BIN" ]; then
        log_error "未找到原版备份: ${CLAWD_ORIG_BIN}"
        exit 1
    fi

    mv "$CLAWD_ORIG_BIN" "$CLAWD_BIN"
    chmod +x "$CLAWD_BIN"
    hash -r 2>/dev/null || true

    log_ok "已恢复到原版"
}

# ===== 主流程 =====
main() {
    # 解析参数
    case "${1:-}" in
        --uninstall)
            uninstall
            exit 0
            ;;
        --revert)
            revert_to_original
            exit 0
            ;;
        --status)
            show_status
            exit 0
            ;;
        --help|-h)
            echo "用法: bash install.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --uninstall    卸载 Clawd Code（保留配置）"
            echo "  --revert       恢复到原版（从备份恢复）"
            echo "  --status       显示安装状态报告"
            echo "  --help, -h     显示帮助"
            echo ""
            echo "借鉴 ClawGod 设计:"
            echo "  clawd          启动增强版"
            echo "  clawd.orig     启动原版（如有备份）"
            echo ""
            exit 0
            ;;
    esac

    echo ""
    echo "╔══════════════════════════════════════════╗"
    echo "║   🦞  Clawd Code 一键安装脚本           ║"
    echo "║   Inspired by Project B (ClawGod)       ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""

    check_prerequisites
    create_virtualenv
    install_dependencies
    create_launcher
    create_default_config
    setup_shell_integration
    print_post_install
}

main "$@"
