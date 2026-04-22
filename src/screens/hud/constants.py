"""HUD 常量和配置"""


# HUD 预设
HUD_PRESET_MINIMAL = "minimal"
HUD_PRESET_FOCUSED = "focused"
HUD_PRESET_FULL = "full"

# 显示组件顺序
DEFAULT_COMPONENT_ORDER = [
    "git_branch",
    "ralph",
    "ultrawork",
    "autopilot",
    "ralplan",
    "team",
    "turns",
    "tokens",
]

# 分隔符
SEPARATOR = " | "

# 颜色代码 (ANSI)
class ANSI:
    """ANSI颜色代码"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

# Ralph 进度颜色阈值
RALPH_COLOR_THRESHOLDS = [
    (0.0, 0.3, ANSI.GREEN),    # 0-30%: 绿色
    (0.3, 0.7, ANSI.YELLOW),   # 30-70%: 黄色
    (0.7, 1.0, ANSI.RED),      # 70-100%: 红色
]

# 令牌数格式化
def format_token_count(value: int) -> str:
    """格式化令牌计数"""
    if value >= 1_000_000:
        return f"{(value / 1_000_000):.1f}M"
    if value >= 1_000:
        return f"{(value / 1_000):.1f}k"
    return str(value)
