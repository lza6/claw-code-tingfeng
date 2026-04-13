"""灵活搜索替换引擎 — 从 aider search_replace.py 移植并增强

提供多种策略的搜索替换功能，处理 LLM 常见的空白和缩进错误。

核心特性:
- RelativeIndenter: 相对缩进转换，处理不同嵌套层级的代码匹配
- flexible_search_and_replace: 多策略矩阵自动回退
- Git cherry-pick 策略: 利用 git 的 diff3 合并算法处理模糊匹配
- DMP (diff-match-patch) 策略: 行级和字符级模糊补丁
- 纯标准库实现，无外部依赖
"""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ==================== 相对缩进器 ====================

class RelativeIndenter:
    """相对缩进转换器 — 从 Aider 完整移植

    将绝对缩进的代码转换为相对缩进，使得在不同嵌套层级的代码也能匹配。

    工作原理:
    - make_relative: 计算每行与前一行之间的缩进差异
      - 增加缩进: 保留增量空白
      - 减少缩进: 用 marker 字符（←）表示减少量
      - 缩进不变: 输出空行 + 无缩进内容
    - make_absolute: 反向转换，恢复绝对缩进

    示例:
        原始代码:          转换后:
            Foo        →       Foo
                Bar    →       Bar
                Baz    →   Baz
            Fob        →   ←←←←Fob
    """

    ARROW = '\u2190'  # ←

    def __init__(self, texts: list[str] | None = None) -> None:
        """初始化

        参数:
            texts: 参考文本列表，用于选择不冲突的 marker 字符。
                   如果 None，默认使用 ←。
        """
        self.marker = self.ARROW

        if texts:
            chars = set()
            for text in texts:
                chars.update(text)
            if self.ARROW not in chars:
                self.marker = self.ARROW
            else:
                self.marker = self._select_unique_marker(chars)

    @staticmethod
    def _select_unique_marker(chars: set[str]) -> str:
        """选择一个不在文本中的 Unicode marker"""
        for codepoint in range(0x10FFFF, 0x10000, -1):
            marker = chr(codepoint)
            if marker not in chars:
                return marker
        raise ValueError('Could not find a unique marker')

    def make_relative(self, text: str) -> str:
        """将绝对缩进转换为相对缩进

        参数:
            text: 绝对缩进的文本

        返回:
            相对缩进的文本（交替行: 缩进增量行 + 内容行）

        异常:
            ValueError: 文本已包含 marker 字符
        """
        if not text:
            return text

        if self.marker in text:
            raise ValueError(f'Text already contains the outdent marker: {self.marker}')

        lines = text.splitlines(keepends=True)
        result: list[str] = []
        prev_indent = ''

        for line in lines:
            line_without_end = line.rstrip('\n\r')
            len_indent = len(line_without_end) - len(line_without_end.lstrip())
            indent = line[:len_indent]
            change = len_indent - len(prev_indent)

            if change > 0:
                cur_indent = indent[-change:]
            elif change < 0:
                cur_indent = self.marker * (-change)
            else:
                cur_indent = ''

            out_line = cur_indent + '\n' + line[len_indent:]
            result.append(out_line)
            prev_indent = indent

        return ''.join(result)

    def make_absolute(self, text: str) -> str:
        """将相对缩进转换回绝对缩进

        参数:
            text: 相对缩进的文本

        返回:
            绝对缩进的文本

        异常:
            ValueError: 转换失败（残留未解析的 marker）
        """
        if not text:
            return text

        lines = text.splitlines(keepends=True)
        result: list[str] = []
        prev_indent = ''

        i = 0
        while i < len(lines):
            dent = lines[i].rstrip('\r\n')
            if i + 1 < len(lines):
                non_indent = lines[i + 1]
            else:
                non_indent = '\n'

            if dent.startswith(self.marker):
                len_outdent = len(dent)
                cur_indent = prev_indent[:-len_outdent] if len_outdent <= len(prev_indent) else ''
            else:
                cur_indent = prev_indent + dent

            stripped = non_indent.rstrip('\r\n')
            if not stripped:
                out_line = non_indent
            else:
                out_line = cur_indent + non_indent

            result.append(out_line)
            prev_indent = cur_indent
            i += 2

        res = ''.join(result)
        if self.marker in res:
            raise ValueError('Error transforming text back to absolute indents')

        return res


# ==================== 预处理器 ====================

def strip_blank_lines(text: str) -> str:
    """去除文本前后的空行（保留内部空行）

    参数:
        text: 输入文本

    返回:
        去除前后空行的文本
    """
    lines = text.splitlines(keepends=True)
    # 去除前导空行
    while lines and not lines[0].strip():
        lines.pop(0)
    # 去除尾部空行
    while lines and not lines[-1].strip():
        lines.pop()
    return ''.join(lines)


def reverse_lines(text: str) -> str:
    """反转文本行顺序（用于匹配文件末尾的代码）

    参数:
        text: 输入文本

    返回:
        行顺序反转的文本
    """
    lines = text.splitlines(keepends=True)
    lines.reverse()
    return ''.join(lines)


# ==================== 搜索替换策略 ====================

def search_and_replace(
    content: str,
    search_text: str,
    replace_text: str,
) -> str:
    """简单精确搜索替换

    在 content 中查找 search_text 并替换为 replace_text。
    search_text 必须恰好出现一次。

    参数:
        content: 原始文件内容
        search_text: 要搜索的文本
        replace_text: 替换文本

    返回:
        替换后的内容

    异常:
        ValueError: 未找到匹配或存在多个匹配
    """
    if not search_text:
        raise ValueError('搜索文本不能为空')

    count = content.count(search_text)
    if count == 0:
        raise ValueError('未找到匹配的搜索文本')
    if count > 1:
        raise ValueError(f'搜索文本在文件中出现了 {count} 次，无法确定唯一匹配位置')

    return content.replace(search_text, replace_text, 1)


def git_cherry_pick_osr_onto_o(
    content: str,
    search_text: str,
    replace_text: str,
) -> str:
    """Git cherry-pick 搜索替换策略 — 从 Aider 移植

    利用 git 的 diff3 合并算法来应用搜索替换：
    1. 创建临时 git 仓库
    2. 提交 original → search → replace
    3. 回到 original，cherry-pick replace
    4. 如果合并成功，返回结果

    参数:
        content: 原始文件内容
        search_text: LLM 认为当前文件中存在的文本
        replace_text: 替换后的文本

    返回:
        替换后的内容

    异常:
        ValueError: cherry-pick 合并冲突
    """
    try:
        import git as gitmod
    except ImportError:
        raise ValueError('gitpython not installed')

    with tempfile.TemporaryDirectory() as dname:
        repo = gitmod.Repo(dname)
        fname = Path(dname) / 'file.txt'

        # O → S → R
        fname.write_text(content, encoding='utf-8')
        repo.git.add(str(fname))
        repo.git.commit('-m', 'original')

        fname.write_text(search_text, encoding='utf-8')
        repo.git.add(str(fname))
        repo.git.commit('-m', 'search')

        fname.write_text(replace_text, encoding='utf-8')
        repo.git.add(str(fname))
        replace_hash = repo.head.commit.hexsha

        # 回到 original
        original_hash = repo.head.commit.parents[0].parents[0].hexsha
        repo.git.checkout(original_hash)

        # cherry-pick R onto original
        try:
            repo.git.cherry_pick(replace_hash, '--minimal')
        except (gitmod.exc.ODBError, gitmod.exc.GitError):
            raise ValueError('git cherry-pick merge conflict')

        return fname.read_text(encoding='utf-8')


def dmp_lines_apply(
    content: str,
    search_text: str,
    replace_text: str,
) -> str:
    """DMP 行级补丁策略 — 从 Aider 移植

    使用 diff-match-patch 的行级 diff 算法应用搜索替换。
    比 search_and_replace 更灵活，能处理空白差异。

    参数:
        content: 原始文件内容
        search_text: 搜索文本
        replace_text: 替换文本

    返回:
        替换后的内容

    异常:
        ValueError: patch 应用失败或缺少依赖
    """
    try:
        from diff_match_patch import diff_match_patch
    except ImportError:
        raise ValueError('diff-match-patch not installed')

    dmp = diff_match_patch()
    dmp.Diff_Timeout = 5
    dmp.Match_Threshold = 0.1
    dmp.Match_Distance = 100_000
    dmp.Match_MaxBits = 32
    dmp.Patch_Margin = 1

    all_text = search_text + replace_text + content
    all_lines, _, mapping = dmp.diff_linesToChars(all_text, '')

    search_num = len(search_text.splitlines())
    replace_num = len(replace_text.splitlines())
    len(content.splitlines())

    search_lines = all_lines[:search_num]
    replace_lines = all_lines[search_num:search_num + replace_num]
    original_lines = all_lines[search_num + replace_num:]

    diff_lines = dmp.diff_main(search_lines, replace_lines, None)
    dmp.diff_cleanupSemantic(diff_lines)
    dmp.diff_cleanupEfficiency(diff_lines)

    patches = dmp.patch_make(search_lines, diff_lines)
    new_lines, success = dmp.patch_apply(patches, original_lines)

    if False in success:
        raise ValueError('DMP patch application failed')

    # 将行号映射回字符
    new_text = ''.join(mapping[ord(char)] for char in new_lines)
    return new_text


@dataclass
class SearchResult:
    """搜索替换结果"""
    success: bool
    content: str
    strategy_used: str = ''
    error: str = ''


def try_strategy(
    content: str,
    search_text: str,
    replace_text: str,
    strategy_fn,
    preprocessors: tuple[bool, bool, bool],
) -> SearchResult:
    """应用预处理策略后执行搜索替换

    参数:
        content: 原始文件内容
        search_text: 搜索文本
        replace_text: 替换文本
        strategy_fn: 搜索替换策略函数
        preprocessors: (strip_blank_lines, relative_indent, reverse_lines)

    返回:
        SearchResult
    """
    s_bl, r_ind, rev = preprocessors

    # 预处理
    proc_search = search_text
    proc_content = content

    if rev:
        proc_search = reverse_lines(proc_search)
        proc_content = reverse_lines(proc_content)

    if s_bl:
        proc_search = strip_blank_lines(proc_search)
        proc_content = strip_blank_lines(proc_content)

    if r_ind:
        texts = [proc_search, replace_text, proc_content]
        ri = RelativeIndenter(texts)
        proc_search, _, proc_content = [
            ri.make_relative(t) for t in texts
        ]

    # 执行策略
    try:
        result = strategy_fn(proc_content, proc_search, replace_text)
        # 反向预处理
        if r_ind:
            ri2 = RelativeIndenter()
            result = ri2.make_absolute(result)
        if rev:
            result = reverse_lines(result)
        return SearchResult(success=True, content=result, strategy_used=strategy_fn.__name__)
    except (ValueError, IndexError, OSError):
        return SearchResult(success=False, content=content, error='未找到匹配')


# ==================== 策略矩阵 ====================

# 预处理器组合: (strip_blank_lines, relative_indent, reverse_lines)
all_preprocs = [
    (False, False, False),
    (True, False, False),
    (False, True, False),
    (True, True, False),
]

# 编辑块策略矩阵
editblock_strategies = [
    (search_and_replace, all_preprocs),
    (git_cherry_pick_osr_onto_o, all_preprocs),
    (dmp_lines_apply, all_preprocs),
]

# UDiff 策略矩阵
udiff_strategies = [
    (search_and_replace, all_preprocs),
    (git_cherry_pick_osr_onto_o, all_preprocs),
    (dmp_lines_apply, all_preprocs),
]


def flexible_search_and_replace(
    content: str,
    search_text: str,
    replace_text: str,
    strategies: list | None = None,
) -> str:
    """灵活搜索替换 — 多策略矩阵自动回退

    按策略优先级尝试多种搜索替换方法:
    1. search_and_replace (精确匹配)
    2. git_cherry_pick_osr_onto_o (git diff3 合并)
    3. dmp_lines_apply (DMP 行级补丁)

    每种策略可配合预处理器组合:
    - strip_blank_lines: 去除前后空行
    - relative_indent: 相对缩进转换
    - 以上组合

    参数:
        content: 原始文件内容
        search_text: 搜索文本
        replace_text: 替换文本
        strategies: 自定义策略矩阵，默认使用 editblock_strategies

    返回:
        替换后的内容

    异常:
        ValueError: 所有策略均失败
    """
    if strategies is None:
        strategies = editblock_strategies

    for strategy_fn, preprocs in strategies:
        for preproc in preprocs:
            # 第一次直接尝试精确匹配（不做预处理）
            if preproc == (False, False, False) and strategy_fn is search_and_replace:
                try:
                    return search_and_replace(content, search_text, replace_text)
                except ValueError:
                    continue

            result = try_strategy(content, search_text, replace_text, strategy_fn, preproc)
            if result.success:
                logger.debug(f'搜索替换成功: strategy={result.strategy_used}, preproc={preproc}')
                return result.content

    raise ValueError(
        f'所有搜索替换策略均失败。\n'
        f'搜索文本前100字符: {search_text[:100]!r}\n'
        f'文件内容前100字符: {content[:100]!r}'
    )
