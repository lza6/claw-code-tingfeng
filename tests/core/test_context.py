"""上下文模块测试"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.context import PortContext, build_port_context, render_context


class TestPortContext:
    """PortContext 数据类测试"""

    def test_port_context_creation(self):
        """测试 PortContext 创建"""
        ctx = PortContext(
            source_root=Path('/src'),
            tests_root=Path('/tests'),
            assets_root=Path('/assets'),
            archive_root=Path('/archive'),
            python_file_count=10,
            test_file_count=5,
            asset_file_count=3,
            archive_available=True,
        )
        assert ctx.source_root == Path('/src')
        assert ctx.python_file_count == 10
        assert ctx.archive_available is True

    def test_port_context_is_frozen(self):
        """测试 PortContext 不可变 (frozen=True)"""
        ctx = PortContext(
            source_root=Path('/src'),
            tests_root=Path('/tests'),
            assets_root=Path('/assets'),
            archive_root=Path('/archive'),
            python_file_count=0,
            test_file_count=0,
            asset_file_count=0,
            archive_available=False,
        )
        # frozen dataclass 会在 setattr 时抛出 FrozenInstanceError
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.python_file_count = 100  # type: ignore[misc]


class TestBuildContext:
    """build_port_context 函数测试"""

    @patch('src.core.context.Path.rglob')
    @patch('src.core.context.Path.exists')
    def test_build_port_context(self, mock_exists, mock_rglob):
        """测试构建 PortContext"""
        # 模拟文件计数
        mock_rglob.return_value = [Path('file1.py'), Path('file2.py')]
        mock_exists.return_value = True

        base = Path('/fake/base')
        ctx = build_port_context(base=base)

        assert ctx.source_root == base / 'src'
        assert ctx.tests_root == base / 'tests'
        assert ctx.assets_root == base / 'assets'
        assert ctx.archive_root == base / 'archive' / 'claude_code_ts_snapshot' / 'src'
        assert ctx.archive_available is True


class TestRenderContext:
    """render_context 函数测试"""

    def test_render_context(self):
        """测试渲染上下文"""
        ctx = PortContext(
            source_root=Path('/src'),
            tests_root=Path('/tests'),
            assets_root=Path('/assets'),
            archive_root=Path('/archive'),
            python_file_count=100,
            test_file_count=50,
            asset_file_count=20,
            archive_available=True,
        )
        rendered = render_context(ctx)
        # 使用 Path 比较避免编码问题
        assert 'src' in rendered
        assert 'tests' in rendered
        assert '100' in rendered
        assert '50' in rendered
        assert 'True' in rendered
