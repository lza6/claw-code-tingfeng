"""Code Edit — 代码编辑策略模块

借鉴 Aider 的 Coder 策略模式，提供多种代码编辑方式:
- EditBlockCoder: SEARCH/REPLACE 块编辑 (最常用)
- UDiffCoder: Unified Diff 格式编辑
- WholeFileCoder: 整文件替换
- PatchCoder: 多文件 patch 编辑

使用:
    from src.tools_runtime.code_edit import create_coder, apply_edit

    # 方式一: 使用工厂函数
    coder = create_coder("editblock")
    result = coder.apply(content, search_text, replace_text)

    # 方式二: 直接使用函数
    result = apply_edit(content, search_text, replace_text)
"""
from src.tools_runtime.code_edit.base_coder import BaseCoder, EditResult
from src.tools_runtime.code_edit.editblock_coder import EditBlockCoder
from src.tools_runtime.code_edit.fuzzy_matcher import (
    perfect_replace,
    replace_most_similar_chunk,
    try_dotdotdots,
)
from src.tools_runtime.code_edit.patch_coder import PatchCoder
from src.tools_runtime.code_edit.udiff_coder import UDiffCoder, UDiffSimpleCoder

# 导入新增的 Coder
from src.tools_runtime.code_edit.wholefile_coder import (
    SingleWholeFileFuncCoder,
    WholeFileCoder,
    WholeFileFuncCoder,
)

__all__ = [
    # 基类
    "BaseCoder",
    # 具体实现
    "EditBlockCoder",
    "EditResult",
    "PatchCoder",
    "SingleWholeFileFuncCoder",
    "UDiffCoder",
    "UDiffSimpleCoder",
    "WholeFileCoder",
    "WholeFileFuncCoder",
    "apply_edit",
    # 工厂函数
    "create_coder",
    # 模糊匹配函数
    "perfect_replace",
    "replace_most_similar_chunk",
    "try_dotdotdots",
]

# Coder 注册表 (借鉴 Aider 的多格式支持)
_CODER_REGISTRY: dict[str, type[BaseCoder]] = {
    # EditBlock (SEARCH/REPLACE)
    "editblock": EditBlockCoder,
    "diff": EditBlockCoder,  # 别名
    "search_replace": EditBlockCoder,  # 别名
    # WholeFile
    "wholefile": WholeFileCoder,
    "whole": WholeFileCoder,  # Aider 默认
    "wholefile_func": WholeFileFuncCoder,
    "single_wholefile_func": SingleWholeFileFuncCoder,
    # UDiff
    "udiff": UDiffCoder,
    "udiff_simple": UDiffSimpleCoder,
    # Patch
    "patch": PatchCoder,
}


def create_coder(edit_format: str = "editblock") -> BaseCoder:
    """创建指定格式的 Coder 实例

    Args:
        edit_format: 编辑格式，支持:
            - "editblock" / "diff" / "search_replace": SEARCH/REPLACE 块编辑 (最常用)
            - "wholefile" / "whole": 整文件替换 (Aider 默认)
            - "wholefile_func": 函数级整文件编辑
            - "single_wholefile_func": 单文件函数级编辑
            - "udiff": 标准 Unified Diff 格式
            - "udiff_simple": 简化版 UDiff
            - "patch": 多文件 patch 格式

    Returns:
        Coder 实例

    Raises:
        ValueError: 不支持的编辑格式
    """
    if edit_format not in _CODER_REGISTRY:
        valid_formats = list(_CODER_REGISTRY.keys())
        raise ValueError(f"Unknown edit format: {edit_format}. Valid formats: {valid_formats}")

    return _CODER_REGISTRY[edit_format]()


def apply_edit(
    content: str,
    search_text: str,
    replace_text: str,
    edit_format: str = "editblock",
    fuzzy: bool = True,
) -> EditResult:
    """应用编辑到内容

    Args:
        content: 原始文件内容
        search_text: 要搜索的文本
        replace_text: 替换文本
        edit_format: 编辑格式
        fuzzy: 是否启用模糊匹配

    Returns:
        EditResult 对象
    """
    coder = create_coder(edit_format)
    return coder.apply(content, search_text, replace_text, fuzzy=fuzzy)
