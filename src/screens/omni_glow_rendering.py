"""Omni-Glow 渲染工具

包含:
- Braille 盲文字符映射
- 2x2 Block 字符渲染
- 进度条渲染
"""


# ============================================================================
# Braille 渲染工具
# ============================================================================

# 盲文字符映射 (2x2)
BRAILLE_DOTS = {
    (0, 0): '\u2801',  # ⠁
    (1, 0): '\u2802',  # ⠂
    (2, 0): '\u2804',  # ⠄
    (0, 1): '\u2808',  # ⠈
    (1, 1): '\u2810',  # ⠐
    (2, 1): '\u2820',  # ⠠
}

# 2x2 Block 字符
BLOCK_CHARS = {
    0: ' ',      # 空
    1: '▘',      # 左上
    2: '▝',      # 右上
    3: '▀',      # 上半
    4: '▖',      # 左下
    5: '▌',      # 左半
    6: '▞',      # 左+右上
    7: '▛',      # 左+上+右上
    8: '▗',      # 右下
    9: '▚',      # 对角
    10: '▐',     # 右半
    11: '▜',     # 右+上+左下
    12: '▄',     # 下半
    13: '▙',     # 左+下+上
    14: '▟',     # 右+下
    15: '█',     # 全满
}


def render_braille_connection(confidence: float) -> str:
    """渲染盲文连接符

    根据置信度显示不同的盲文符号
    """
    if confidence >= 0.8:
        return '⣿'  # 高置信度
    elif confidence >= 0.5:
        return '⣾'  # 中置信度
    else:
        return '⣀'  # 低置信度


def render_block_progress(value: float, width: int = 20) -> str:
    """使用 2x2 Block 字符渲染进度

    参数:
        value: 进度 [0, 1]
        width: 宽度 (字符数)

    返回:
        Block 进度条字符串
    """
    filled = int(value * width)
    empty = width - filled

    if filled > 0:
        bar = '█' * filled
    else:
        bar = ''

    if empty > 0:
        bar += '░' * empty

    return bar
