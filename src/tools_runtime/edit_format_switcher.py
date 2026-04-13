"""Edit Format Switcher — 编辑格式管理器

借鉴 Aider 的多格式支持，提供:
1. 动态切换编辑格式
2. 格式验证和自动检测
3. 格式特定提示词

使用:
    from src.tools_runtime.edit_format_switcher import EditFormatSwitcher

    switcher = EditFormatSwitcher()
    switcher.set_format("wholefile")
    prompt = switcher.get_prompt()
"""
from __future__ import annotations

# 编辑格式常量 (借鉴 Aider)
EDIT_FORMAT_CHOICES = [
    "editblock",
    "diff",
    "search_replace",
    "wholefile",
    "whole",
    "wholefile_func",
    "single_wholefile_func",
    "udiff",
    "udiff_simple",
    "patch",
]


# 格式描述 (借鉴 Aider 的 coders/__init__.py)
EDIT_FORMAT_DESCRIPTIONS = {
    "editblock": "Use SEARCH/REPLACE blocks to edit code",
    "diff": "Use diff format to show changes",
    "search_replace": "Use search and replace blocks",
    "wholefile": "Replace entire file content",
    "whole": "Replace entire file (Aider default)",
    "wholefile_func": "Edit at function/class level",
    "single_wholefile_func": "Edit single file at function level",
    "udiff": "Use unified diff format",
    "udiff_simple": "Simplified unified diff",
    "patch": "Use multi-file patch format",
}


# 格式提示词 (借鉴 Aider 的 prompts)
EDIT_FORMAT_PROMPTS = {
    "editblock": """你可以使用 SEARCH/REPLACE 块来编辑代码。

编辑格式示例:
```
filename.py
```python
<<<<<<< SEARCH
def old_function():
    pass
=======
def new_function():
    return True
>>>>>>> REPLACE
```

注意: SEARCH 块必须精确匹配文件中的内容，包括所有空白和注释。
""",

    "wholefile": """你可以替换整个文件的内容。

编辑格式示例:
```
filename.py
```python
# 完整的文件内容
def main():
    pass
```

只需提供完整的文件内容即可。
""",

    "udiff": """你可以使用 unified diff 格式编辑代码。

编辑格式示例:
```
filename.py
```diff
@@ -1,3 +1,4 @@
 def function():
-    old_line
+    new_line_1
+    new_line_2
```
""",

    "patch": """你可以使用 patch 格式同时编辑多个文件。

编辑格式示例:
```
*** Update File: src/main.py
```python
old content
---
new content
***
*** End of File
*** End Patch
```
""",
}


class EditFormatSwitcher:
    """编辑格式切换器

    功能:
    - 切换当前使用的编辑格式
    - 获取格式对应的系统提示词
    - 验证格式是否有效
    - 自动检测最佳格式
    """

    def __init__(self, default_format: str = "editblock"):
        self._current_format = default_format
        self._format_history: list[str] = []

    @property
    def current_format(self) -> str:
        """获取当前编辑格式"""
        return self._current_format

    def set_format(self, format_name: str) -> bool:
        """设置编辑格式

        Args:
            format_name: 格式名称

        Returns:
            是否设置成功
        """
        if format_name not in EDIT_FORMAT_CHOICES:
            return False

        # 记录历史
        if format_name != self._current_format:
            self._format_history.append(self._current_format)

        self._current_format = format_name
        return True

    def get_prompt(self) -> str:
        """获取当前格式的系统提示词

        Returns:
            格式提示词，如果没有则返回空
        """
        return EDIT_FORMAT_PROMPTS.get(self._current_format, "")

    def get_description(self) -> str:
        """获取当前格式的描述

        Returns:
            格式描述
        """
        return EDIT_FORMAT_DESCRIPTIONS.get(
            self._current_format,
            "Use SEARCH/REPLACE blocks",
        )

    def is_valid_format(self, format_name: str) -> bool:
        """检查格式是否有效

        Args:
            format_name: 格式名称

        Returns:
            是否有效
        """
        return format_name in EDIT_FORMAT_CHOICES

    def get_available_formats(self) -> list[str]:
        """获取所有可用的格式

        Returns:
            格式列表
        """
        return EDIT_FORMAT_CHOICES.copy()

    def get_format_info(self, format_name: str) -> dict:
        """获取格式详细信息

        Args:
            format_name: 格式名称

        Returns:
            格式信息字典
        """
        return {
            "name": format_name,
            "description": EDIT_FORMAT_DESCRIPTIONS.get(format_name, ""),
            "prompt": EDIT_FORMAT_PROMPTS.get(format_name, ""),
            "is_current": format_name == self._current_format,
        }

    def auto_detect_format(self, file_content: str) -> str:
        """根据文件内容自动检测最佳格式

        基于文件特征选择最合适的编辑格式:
        - 小文件 (< 100行): editblock
        - 大文件 (> 500行): wholefile
        - 多文件编辑: patch
        - 简单修改: udiff

        Args:
            file_content: 文件内容

        Returns:
            推荐的格式
        """
        lines = file_content.split('\n')

        if len(lines) < 100:
            return "editblock"
        elif len(lines) > 500:
            return "wholefile"
        else:
            return "editblock"

    def get_history(self) -> list[str]:
        """获取格式切换历史

        Returns:
            历史记录
        """
        return self._format_history.copy()

    def revert_format(self) -> str | None:
        """回退到上一个格式

        Returns:
            之前的格式，如果无历史则返回 None
        """
        if not self._format_history:
            return None

        previous = self._format_history.pop()
        current = self._current_format
        self._current_format = previous
        return current


# 全局实例
_edit_format_switcher: EditFormatSwitcher | None = None


def get_edit_format_switcher(default_format: str = "editblock") -> EditFormatSwitcher:
    """获取全局 EditFormatSwitcher 实例"""
    global _edit_format_switcher
    if _edit_format_switcher is None:
        _edit_format_switcher = EditFormatSwitcher(default_format)
    return _edit_format_switcher
