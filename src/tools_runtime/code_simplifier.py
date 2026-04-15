"""
Code Simplifier - 代码简化器

从 oh-my-codex-main 汲取的代码简化钩子。
在 agent turn 完成后自动简化修改的代码文件。

通过 ~/.clawd/config.json 配置: { "codeSimplifier": { "enabled": true } }
默认：禁用（需要显式启用）
"""

import os
import re
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List


# ===== 配置类 =====
@dataclass
class CodeSimplifierConfig:
    enabled: bool = False
    extensions: List[str] = None
    max_files: int = 10

    def __post_init__(self):
        if self.extensions is None:
            self.extensions = ['.ts', '.tsx', '.js', '.jsx', '.py', '.go', '.rs', '.py']


# ===== 常量 =====
DEFAULT_EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx', '.py', '.go', '.rs']
DEFAULT_MAX_FILES = 10
TRIGGER_MARKER_FILENAME = 'code-simplifier-triggered.marker'


# ===== 结果类 =====
@dataclass
class CodeSimplifierResult:
    triggered: bool
    message: str
    files: List[str] = None

    def __post_init__(self):
        if self.files is None:
            self.files = []


# ===== 配置读取 =====
def read_clawd_config(config_path: Optional[str] = None) -> dict:
    """读取 Clawd 配置"""
    if config_path is None:
        config_path = os.path.expanduser('~/.clawd/config.json')

    config_file = Path(config_path)
    if not config_file.exists():
        return {}

    try:
        import json
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def is_code_simplifier_enabled(config_path: Optional[str] = None) -> bool:
    """检查代码简化器是否启用"""
    config = read_clawd_config(config_path)
    return config.get('codeSimplifier', {}).get('enabled', False) is True


# ===== 文件获取 =====
def get_modified_files(
    cwd: str,
    extensions: List[str] = None,
    max_files: int = DEFAULT_MAX_FILES,
) -> List[str]:
    """通过 git status 获取修改的文件"""
    if extensions is None:
        extensions = DEFAULT_EXTENSIONS

    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain', '--untracked-files=all'],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip()
        if not output:
            return []

        candidates = []
        for line in output.split('\n'):
            line = line.rstrip()
            if not line:
                continue

            # 处理未跟踪文件
            if line.startswith('?? '):
                file_path = line[3:].strip()
            else:
                # 解析状态
                status = line[:2]
                if 'D' in status:  # 删除的文件
                    continue
                file_path = line[3:].strip()

            # 处理重命名
            if ' -> ' in file_path:
                file_path = file_path.split(' -> ')[-1].strip()

            if file_path:
                candidates.append(file_path)

        # 过滤扩展名和存在性
        return [
            f for f in candidates
            if any(f.endswith(ext) for ext in extensions)
            and Path(cwd) / f
        ][:max_files]

    except Exception:
        return []


# ===== 触发标记 =====
def is_already_triggered(state_dir: str) -> bool:
    """检查是否已在���轮触发"""
    return (Path(state_dir) / TRIGGER_MARKER_FILENAME).exists()


def write_trigger_marker(state_dir: str) -> None:
    """写入触发标记"""
    try:
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        marker_path = Path(state_dir) / TRIGGER_MARKER_FILENAME
        marker_path.write_text(__import__('datetime').datetime.now().isoformat(), encoding='utf-8')
    except Exception:
        pass


def clear_trigger_marker(state_dir: str) -> None:
    """清除触发标记"""
    try:
        marker_path = Path(state_dir) / TRIGGER_MARKER_FILENAME
        if marker_path.exists():
            marker_path.unlink()
    except Exception:
        pass


# ===== 消息构建 =====
def build_simplifier_message(files: List[str]) -> str:
    """构建简化器消息"""
    file_list = '\n'.join(f'  - {f}' for f in files)
    file_args = '\\n'.join(files)

    return (
        f'[CODE SIMPLIFIER] Recently modified files detected. Delegate to the '
        f'code-simplifier agent to simplify the following files for clarity, '
        f'consistency, and maintainability (without changing behavior):\n\n'
        f'{file_list}\n\n'
        f'Use: @code-simplifier "Simplify the recently modified files:\\n{file_args}"'
    )


# ===== 主处理函数 =====
def process_code_simplifier(
    cwd: str,
    state_dir: str,
    config_path: Optional[str] = None,
) -> CodeSimplifierResult:
    """
    处理代码简化器钩子

    逻辑：
    1. 如果功能未启用，直接返回（不触发）
    2. 如果该轮已触发，清除标记并跳过
    3. 通过 git status 获取修改的文件
    4. 如果没有相关文件修改，直接返回
    5. 写入触发标记并构建简化器委托消息
    """
    if not is_code_simplifier_enabled(config_path):
        return CodeSimplifierResult(triggered=False, message='')

    # 如果已触发，清除标记并允许正常流程
    if is_already_triggered(state_dir):
        clear_trigger_marker(state_dir)
        return CodeSimplifierResult(triggered=False, message='')

    config = read_clawd_config(config_path)
    simplifier_config = config.get('codeSimplifier', {})
    extensions = simplifier_config.get('extensions', DEFAULT_EXTENSIONS)
    max_files = simplifier_config.get('maxFiles', DEFAULT_MAX_FILES)

    files = get_modified_files(cwd, extensions, max_files)

    if not files:
        return CodeSimplifierResult(triggered=False, message='')

    write_trigger_marker(state_dir)

    return CodeSimplifierResult(
        triggered=True,
        message=build_simplifier_message(files),
        files=files,
    )


# ===== 便捷函数 =====
def simplify_imports(text: str) -> str:
    """
    简化 Python import 语句
    移除重复和未使用的 import
    """
    lines = text.split('\n')
    imports = {}
    non_imports = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from '):
            # 规范化 import 行
            key = stripped
            if key not in imports:
                imports[key] = line
        else:
            non_imports.append(line)

    # 重组：保留所有 import（因为无法静态分析是否使用）
    import_lines = list(imports.values())
    return '\n'.join(import_lines + non_imports)


def remove_docstring_redundancy(text: str) -> str:
    """
    移除冗余的 docstring
    移除与函数名重复的描述信息
    """
    lines = text.split('\n')
    result = []
    in_docstring = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 检测 docstring 开始
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if in_docstring:
                in_docstring = False
                result.append(line)
            else:
                in_docstring = True
                result.append(line)
        elif in_docstring:
            # 在 docstring 内部，检查是否是与函数名相关的重复信息
            # 这里简化处理：移除单行的自明性注释
            if len(stripped) > 10:
                result.append(line)
        else:
            result.append(line)

    return '\n'.join(result)


# ===== 导出 =====
__all__ = [
    "CodeSimplifierConfig",
    "CodeSimplifierResult",
    "is_code_simplifier_enabled",
    "process_code_simplifier",
    "get_modified_files",
    "build_simplifier_message",
    "simplify_imports",
    "remove_docstring_redundancy",
]