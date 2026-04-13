"""Git 工具集 — 从 aider repo.py 移植核心模式

提供增强的 Git 操作功能:
- tracked files 缓存
- AI 归属提交
- 智能提交消息生成
- undo 操作
- .clawdignore 支持
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class GitRepo:
    """Git 仓库操作封装

    封装常用 Git 操作，提供:
    - 文件追踪列表（带缓存）
    - 智能提交（AI 归属 + co-authored-by）
    - undo（软重置）
    - ignore 文件检查（.gitignore + .clawdignore）
    """

    def __init__(self, root: str | None = None) -> None:
        """初始化 Git 仓库

        参数:
            root: 仓库根目录（默认自动检测）
        """
        if root is None:
            root = self._find_repo_root()
        self.root = root
        self.is_repo = self._check_is_repo()
        self._tracked_files_cache: dict[str, list[str]] = {}
        self._current_commit: str | None = None

    @staticmethod
    def _find_repo_root() -> str:
        """查找当前目录的 Git 仓库根目录"""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return os.getcwd()

    def _check_is_repo(self) -> bool:
        """检查是否为有效的 Git 仓库"""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                capture_output=True, text=True, timeout=10,
                cwd=self.root,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _run_git(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        """执行 Git 命令

        参数:
            args: Git 命令参数
            timeout: 超时秒数

        返回:
            subprocess.CompletedProcess
        """
        return subprocess.run(
            ['git', *list(args)],
            capture_output=True, text=True, timeout=timeout,
            cwd=self.root,
        )

    def get_tracked_files(self) -> list[str]:
        """获取所有已追踪的文件列表

        使用 git ls-files 列出所有已提交和已暂存的文件。
        结果按 commit hash 缓存。

        返回:
            标准化路径的文件列表（正斜杠，无前导 ./）
        """
        if not self.is_repo:
            return []

        # 获取当前 commit hash
        result = self._run_git('rev-parse', 'HEAD')
        commit_hash = result.stdout.strip() if result.returncode == 0 else 'working-tree'

        if commit_hash in self._tracked_files_cache:
            return self._tracked_files_cache[commit_hash]

        # 列出所有已追踪文件
        result = self._run_git('ls-files')
        if result.returncode != 0:
            return []

        files = []
        for line in result.stdout.splitlines():
            # 标准化路径
            normalized = line.strip().replace('\\', '/')
            if normalized and not normalized.startswith('./'):
                normalized = './' + normalized
            files.append(normalized)

        self._tracked_files_cache[commit_hash] = files
        return files

    def get_dirty_files(self) -> list[str]:
        """获取所有修改过的文件（已暂存 + 未暂存）

        返回:
            修改文件路径列表
        """
        if not self.is_repo:
            return []

        dirty: list[str] = []

        # 已暂存的文件
        result = self._run_git('diff', '--name-only', '--cached')
        if result.returncode == 0:
            dirty.extend(result.stdout.strip().splitlines())

        # 未暂存的文件
        result = self._run_git('diff', '--name-only')
        if result.returncode == 0:
            dirty.extend(result.stdout.strip().splitlines())

        # 未追踪的文件
        result = self._run_git('ls-files', '--others', '--exclude-standard')
        if result.returncode == 0:
            dirty.extend(result.stdout.strip().splitlines())

        return [f.replace('\\', '/') for f in dirty if f.strip()]

    def get_diffs(self, fnames: list[str] | None = None) -> str:
        """生成 unified diff

        参数:
            fnames: 指定文件列表（None 表示所有 dirty 文件）

        返回:
            unified diff 字符串
        """
        if not self.is_repo:
            return ''

        if fnames:
            args = ['diff', 'HEAD', '--', *fnames]
        else:
            args = ['diff', 'HEAD']

        result = self._run_git(*args, timeout=60)
        if result.returncode != 0:
            # 空分支（无 commit）时尝试 diff --cached
            result = self._run_git('diff', '--cached', '--')
            if result.returncode != 0:
                return ''

        return result.stdout

    def commit(
        self,
        fnames: list[str],
        message: str,
        attribute: bool = True,
        co_author: str = 'Clawd Code',
    ) -> str:
        """智能提交

        参数:
            fnames: 要提交的文件列表
            message: 提交消息
            attribute: 是否添加 AI 归属
            co_author: co-authored-by 中的 AI 名称

        返回:
            commit hash（短格式）
        """
        if not self.is_repo:
            raise RuntimeError('不在 Git 仓库中')

        # 暂存指定文件
        self._run_git('add', '--', *fnames)

        # 添加 co-authored-by trailer
        if attribute:
            trailer = f'Co-authored-by: {co_author} <clawd@clawd.ai>'
            message = message.rstrip() + f'\n\n{trailer}'

        # 提交
        result = self._run_git('commit', '-m', message)
        if result.returncode != 0:
            raise RuntimeError(f'Git commit 失败: {result.stderr}')

        # 获取 commit hash
        result = self._run_git('rev-parse', '--short', 'HEAD')
        if result.returncode == 0:
            return result.stdout.strip()
        return 'unknown'

    def undo(self) -> bool:
        """撤销最后一次提交（soft reset）

        将最后一次提交的更改保留在工作区。

        返回:
            是否成功
        """
        if not self.is_repo:
            return False

        result = self._run_git('reset', '--soft', 'HEAD~1')
        return result.returncode == 0

    def get_commit_message_suggestion(self, diff: str) -> str:
        """从 diff 生成提交消息建议

        简单启发式方法（非 LLM），分析 diff 生成 conventional-commit 风格的消息。

        参数:
            diff: unified diff 字符串

        返回:
            提交消息建议
        """
        if not diff.strip():
            return 'chore: empty changes'

        # 分析 diff
        files_changed: list[tuple[str, str]] = []  # (filename, change_type)
        added_lines = 0
        removed_lines = 0

        for line in diff.splitlines():
            # 文件名
            match = re.match(r'^\+\+\+ b/(.+)', line)
            if match:
                fname = match.group(1)
                files_changed.append((fname, 'modified'))
                continue

            match = re.match(r'^--- /dev/null', line)
            if match:
                if files_changed:
                    fname, _ = files_changed[-1]
                    files_changed[-1] = (fname, 'added')
                continue

            match = re.match(r'^--- a/(.+)', line)
            if match:
                # 检查是否是删除（+++ /dev/null）
                continue

            match = re.match(r'^\+\+\+ /dev/null', line)
            if match:
                if files_changed:
                    fname, _ = files_changed[-1]
                    files_changed[-1] = (fname, 'deleted')
                continue

            # 统计行数
            if line.startswith('+') and not line.startswith('+++'):
                added_lines += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed_lines += 1

        if not files_changed:
            return 'chore: update'

        # 确定 change type
        types = set(ct for _, ct in files_changed)
        if types == {'added'}:
            prefix = 'feat'
        elif types == {'deleted'}:
            prefix = 'remove'
        elif 'added' in types and 'modified' in types:
            prefix = 'feat'
        else:
            prefix = 'update'

        # 文件摘要
        file_names = [f for f, _ in files_changed[:3]]
        scope = ', '.join(file_names)
        if len(files_changed) > 3:
            scope += f' (+{len(files_changed) - 3} more)'

        # 行数摘要
        summary_parts = []
        if added_lines:
            summary_parts.append(f'+{added_lines}')
        if removed_lines:
            summary_parts.append(f'-{removed_lines}')

        lines_summary = f' ({", ".join(summary_parts)} lines)' if summary_parts else ''

        return f'{prefix}: update {scope}{lines_summary}'

    def is_ignored(self, fname: str) -> bool:
        """检查文件是否被 gitignore 或 clawdignore

        参数:
            fname: 文件路径

        返回:
            是否被忽略
        """
        if not self.is_repo:
            return False

        # 检查 .gitignore
        result = self._run_git('check-ignore', '--quiet', fname)
        if result.returncode == 0:
            return True

        # 检查 .clawdignore
        clawdignore = Path(self.root) / '.clawdignore'
        if clawdignore.exists():
            try:
                content = clawdignore.read_text(encoding='utf-8')
                patterns = [p.strip() for p in content.splitlines() if p.strip() and not p.startswith('#')]
                for pattern in patterns:
                    if self._match_pattern(pattern, fname):
                        return True
            except OSError:
                pass

        return False

    @staticmethod
    def _match_pattern(pattern: str, fname: str) -> bool:
        """简单的 glob 模式匹配

        参数:
            pattern: glob 模式
            fname: 文件名

        返回:
            是否匹配
        """
        import fnmatch
        basename = os.path.basename(fname)
        # 尝试完整路径匹配和基本名匹配
        return fnmatch.fnmatch(fname, pattern) or fnmatch.fnmatch(basename, pattern)

    def path_in_repo(self, path: str) -> bool:
        """检查路径是否在仓库内

        参数:
            path: 要检查的路径

        返回:
            是否在仓库内
        """
        if not self.is_repo:
            return False

        try:
            abs_path = Path(path).resolve()
            repo_path = Path(self.root).resolve()
            return abs_path.is_relative_to(repo_path)
        except (ValueError, OSError):
            return False

    def get_staged_files(self) -> list[str]:
        """获取已暂存的文件列表

        返回:
            已暂存文件路径列表
        """
        if not self.is_repo:
            return []

        result = self._run_git('diff', '--name-only', '--cached')
        if result.returncode != 0:
            return []

        return [f.replace('\\', '/') for f in result.stdout.strip().splitlines() if f.strip()]

    def get_branch_name(self) -> str:
        """获取当前分支名

        返回:
            当前分支名，或 'HEAD'（分离头状态）
        """
        if not self.is_repo:
            return 'unknown'

        result = self._run_git('rev-parse', '--abbrev-ref', 'HEAD')
        if result.returncode == 0:
            return result.stdout.strip()
        return 'unknown'

    def has_uncommitted_changes(self) -> bool:
        """检查是否有未提交的更改

        返回:
            是否有未提交的更改
        """
        return bool(self.get_dirty_files())

    # ==================== 高级功能（移植自 Aider repo.py） ====================

    def get_tree_files(self, commit_hash: str | None = None) -> dict[str, str]:
        """获取指定 commit 的文件树（文件路径 → commit hash）

        参数:
            commit_hash: commit hash（None 表示 HEAD）

        返回:
            {文件路径: blob_hash} 字典
        """
        if not self.is_repo:
            return {}

        cmd = ['git', 'ls-tree', '-r', commit_hash or 'HEAD']
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=self.root,
        )

        tree_files: dict[str, str] = {}
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                # 格式: mode type hash\tpath
                parts = line.split('\t', 1)
                if len(parts) == 2:
                    meta = parts[0].split()
                    if len(meta) >= 3:
                        blob_hash = meta[2]
                        filepath = parts[1].strip()
                        tree_files[filepath] = blob_hash

        return tree_files

    def get_file_commit_hash(self, fname: str) -> str | None:
        """获取文件最新的 commit hash

        参数:
            fname: 文件路径

        返回:
            commit hash，或 None
        """
        if not self.is_repo:
            return None

        result = self._run_git('log', '-1', '--format=%H', '--', fname)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None

    def get_blame_info(self, fname: str, line_start: int = 1, line_end: int | None = None) -> str:
        """获取文件指定行的 blame 信息

        参数:
            fname: 文件路径
            line_start: 起始行号（1-indexed）
            line_end: 结束行号（None 表示文件末尾）

        返回:
            git blame 输出
        """
        if not self.is_repo:
            return ''

        args = ['blame', fname]
        if line_start > 1 or line_end is not None:
            args = ['blame', f'-L{line_start},{line_end or ""}', fname]

        result = self._run_git(*args, timeout=60)
        return result.stdout if result.returncode == 0 else ''

    def get_repo_root(self) -> str:
        """获取仓库根目录的绝对路径

        返回:
            仓库根目录路径
        """
        if self.root:
            return str(Path(self.root).resolve())
        return os.getcwd()

    def normalize_path(self, fname: str) -> str:
        """标准化文件路径（相对于仓库根目录）

        参数:
            fname: 文件路径

        返回:
            标准化后的相对路径
        """
        try:
            abs_path = Path(fname).resolve()
            repo_root = Path(self.root).resolve()
            return str(abs_path.relative_to(repo_root)).replace('\\', '/')
        except (ValueError, OSError):
            return fname.replace('\\', '/')

    def get_aiderignore_patterns(self) -> list[str]:
        """获取 .clawdignore 模式列表

        返回:
            ignore 模式列表
        """
        clawdignore = Path(self.root) / '.clawdignore'
        if not clawdignore.exists():
            return []

        try:
            content = clawdignore.read_text(encoding='utf-8')
            return [
                p.strip() for p in content.splitlines()
                if p.strip() and not p.startswith('#')
            ]
        except OSError:
            return []


# ==================== 便捷函数 ====================

def get_repo(root: str | None = None) -> GitRepo:
    """获取 GitRepo 实例（便捷函数）

    参数:
        root: 仓库根目录

    返回:
        GitRepo 实例
    """
    return GitRepo(root)


def is_git_repo(path: str | None = None) -> bool:
    """检查路径是否在 Git 仓库中

    参数:
        path: 路径（默认当前目录）

    返回:
        是否在 Git 仓库中
    """
    repo = GitRepo(path)
    return repo.is_repo
