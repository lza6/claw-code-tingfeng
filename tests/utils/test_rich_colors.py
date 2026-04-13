"""Rich 颜色测试 - 覆盖 src/utils/rich_colors.py"""

import pytest
from src.utils.rich_colors import (
    BLUE,
    GREEN,
    YELLOW,
    RED,
    PURPLE,
    CYAN,
    GRAY,
    DARK_GRAY,
    WHITE,
    HSL_IDLE,
    HSL_THINKING,
    HSL_ALERT,
    HSL_SUCCESS,
    HSL_WARNING,
    BORDER_PRIMARY,
    BORDER_GLOW,
    BORDER_SUCCESS,
    BORDER_ALERT,
    hsl_to_hex,
    r_primary,
    r_success,
    r_warning,
    r_error,
    r_info,
    r_idle,
    get_console,
)


class TestColorConstants:
    """颜色常量测试"""

    def test_basic_colors(self):
        """测试基础颜色"""
        assert BLUE == "#00d7ff"
        assert GREEN == "#87ff00"
        assert YELLOW == "#ffd700"
        assert RED == "#ff5555"

    def test_state_colors(self):
        """测试状态颜色"""
        assert HSL_IDLE == (230, 20, 15)
        assert HSL_THINKING == (260, 80, 25)
        assert HSL_ALERT == (0, 70, 20)

    def test_border_colors(self):
        """测试边框颜色"""
        assert BORDER_PRIMARY == (190, 80, 50)
        assert BORDER_GLOW == (260, 80, 60)


class TestHslToHex:
    """HSL 转 HEX 测试"""

    def test_black(self):
        """测试黑色"""
        result = hsl_to_hex(0, 0, 0)
        assert result == "#000000"

    def test_white(self):
        """测试白色"""
        result = hsl_to_hex(0, 0, 100)
        assert result == "#ffffff"

    def test_red(self):
        """测试红色"""
        result = hsl_to_hex(0, 100, 50)
        assert result == "#ff0000"

    def test_green(self):
        """测试绿色"""
        result = hsl_to_hex(120, 100, 50)
        assert result == "#00ff00"

    def test_blue(self):
        """测试蓝色"""
        result = hsl_to_hex(240, 100, 50)
        assert result == "#0000ff"

    def test_gray(self):
        """测试灰色 - 允许浮点精度误差"""
        result = hsl_to_hex(0, 0, 50)
        # 50% 灰色可能是 #7f7f7f 或 #808080
        assert result in ("#7f7f7f", "#808080")


class TestRichColorFunctions:
    """Rich 颜色函数测试"""

    def test_r_primary(self):
        """测试主色"""
        result = r_primary("test")
        assert result is not None

    def test_r_success(self):
        """测试成功色"""
        result = r_success("test")
        assert result is not None

    def test_r_warning(self):
        """测试警告色"""
        result = r_warning("test")
        assert result is not None

    def test_r_error(self):
        """测试错误色"""
        result = r_error("test")
        assert result is not None

    def test_r_info(self):
        """测试信息色"""
        result = r_info("test")
        assert result is not None

    def test_r_idle(self):
        """测试空闲色"""
        result = r_idle("test")
        assert result is not None


class TestGetConsole:
    """Console 测试"""

    def test_get_console(self):
        """测试获取 Console"""
        console = get_console()
        assert console is not None