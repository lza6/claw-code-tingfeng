"""路径沙箱守卫 - 防止符号链接逃逸和路径遍历攻击

移植自 oh-my-codex-main/crates/omx-explore/src/main.rs:692-785

核心防护：
1. 路径遍历：禁止 .. 走到沙箱外
2. 符号链接链逃逸：递归解析最多 MAX_SYMLINK_DEPTH 层
3. 安全边界：所有操作必须在 sandbox_root 内
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 配置常量
HARNESS_ROOT_ENV = "CLAWD_SANDBOX_ROOT"
MAX_SYMLINK_DEPTH = 10


@dataclass(frozen=True, slots=True)
class PathValidationResult:
    """路径验证结果"""
    is_valid: bool
    canonical_path: Path | None = None
    error_message: str | None = None
    symlink_chain: list[str] = field(default_factory=list)


def _resolve_symlink_chain(
    target: Path,
    repo_root: Path
) -> tuple[Path, list[str], str]:
    """
    解析符号链接链 - 简化的路径规范化实现

    核心逻辑：
    1. 构建完整路径（不解析符号链接）
    2. 规范化 . 和 ..（基于当前构建的路径）
    3. 检测符号链接并递归处理
    4. 边界检查

    Returns: (最终路径, 链接链, 状态)
    状态: ""=成功, "broken"=损坏, "circular"=循环, "escape"=逃逸
    """
    # Step 1: 从目标构建路径，但不解析符号链接
    # 使用纯字符串/parts 操作来追踪路径
    parts = list(target.parts)
    chain = []
    depth = 0
    seen_inodes: set[str] = set()  # 用于循环检测

    while depth < MAX_SYMLINK_DEPTH:
        # 重建当前完整路径（不跟随符号链接）
        current_path = Path()
        symlink_found = None
        symlink_index = -1

        for i, part in enumerate(parts):
            current_path = current_path / part

            # 检查是否是符号链接（而不解析它）
            if current_path.is_symlink():
                symlink_found = current_path
                symlink_index = i
                break

        if symlink_found is None:
            # 没有更多符号链接，路径构建完成
            break

        # 记录符号链接到链中
        chain.append(str(symlink_found))

        # 读取符号链接目标
        try:
            raw_target = os.readlink(symlink_found)
        except OSError:
            return symlink_found, chain, "broken"

        # 检查循环：通过 inode 或路径指纹
        try:
            stat_info = symlink_found.stat()
            inode_id = f"{stat_info.st_ino}_{stat_info.st_dev}"
            if inode_id in seen_inodes:
                return symlink_found, chain, "circular"
            seen_inodes.add(inode_id)
        except OSError:
            pass  # 无法 stat，继续执行

        # 替换符号链接部分为目标路径
        # parts[0..symlink_index] 是到达符号链接的路径
        # 符号链接本身替换为 raw_target (规范化后)
        before_parts = parts[:symlink_index]
        after_parts = parts[symlink_index + 1:]

        # 规范化符号链接目标
        target_path = Path(raw_target)
        if not target_path.is_absolute():
            # 相对目标：相对于符号链接所在目录
            target_path = symlink_found.parent / raw_target

        # 规范化 . 和 ..
        normalized_parts = []
        for part in target_path.parts:
            if part == '.':
                continue
            elif part == '..':
                if normalized_parts:
                    normalized_parts.pop()
            else:
                normalized_parts.append(part)

        # 重建 parts: before + normalized_target + after
        parts = before_parts + normalized_parts + after_parts
        depth += 1

    # 重建最终路径
    final = Path()
    for part in parts:
        final = final / part

    # 规范化：处理剩余的 ..（如果 final 是相对路径，基于 repo_root）
    # 注意：final 可能不是绝对路径
    try:
        final_abs = final.resolve(strict=False)
    except Exception:
        final_abs = final

    # 边界检查：必须在 repo_root 内
    try:
        final_abs.relative_to(repo_root)
    except ValueError:
        return final_abs, chain, "escape"

    return final_abs, chain, ""


def validate_path_sandbox(
    repo_root: Path | str,
    target_path: Path | str,
) -> PathValidationResult:
    # Empty path check
    if target_path is None:
        return PathValidationResult(False, error_message="path cannot be None")
    if isinstance(target_path, str) and not target_path.strip():
        return PathValidationResult(False, error_message="empty path not allowed")
    if isinstance(target_path, Path) and str(target_path) == "." and not target_path.is_absolute():
        return PathValidationResult(False, error_message="empty path not allowed")

    repo_root_abs = Path(repo_root).resolve()
    target = Path(target_path)

    if not target.is_absolute():
        target = repo_root_abs / target

    canonical, chain, status = _resolve_symlink_chain(target, repo_root_abs)

    if status == "escape":
        return PathValidationResult(
            is_valid=False,
            error_message=f"path escapes sandbox: {canonical} (outside {repo_root_abs})",
            symlink_chain=chain,
        )
    if status == "broken":
        return PathValidationResult(
            is_valid=False,
            error_message="broken symlink or inaccessible target",
            symlink_chain=chain,
        )
    if status == "circular":
        return PathValidationResult(
            is_valid=False,
            error_message="circular symlink detected",
            symlink_chain=chain,
        )

    # Windows \\?\ prefix removal
    final_str = str(canonical)
    if final_str.startswith('\\\\?\\'):
        canonical = Path(final_str[4:])

    # Final boundary check
    try:
        canonical.relative_to(repo_root_abs)
    except ValueError:
        return PathValidationResult(
            is_valid=False,
            error_message=f"path escapes sandbox: {canonical} (outside {repo_root_abs})",
            symlink_chain=chain,
        )

    return PathValidationResult(
        is_valid=True,
        canonical_path=canonical,
        symlink_chain=chain,
    )


def validate_repo_paths(
    command_name: str,
    args: list[str],
    sandbox_root: Path | str | None = None
) -> PathValidationResult | None:
    sandbox_env = HARNESS_ROOT_ENV
    if sandbox_root is None:
        sandbox_root = os.environ.get(sandbox_env)
        if not sandbox_root:
            return None
    sandbox_root = Path(sandbox_root).resolve()

    path_args = _extract_path_arguments(command_name, args)
    if not path_args:
        return None

    for p in path_args:
        r = validate_path_sandbox(sandbox_root, Path(p))
        if not r.is_valid:
            return r
    return PathValidationResult(is_valid=True)


def get_sandbox_root() -> Path | None:
    root = os.environ.get(HARNESS_ROOT_ENV)
    return Path(root).resolve() if root else None


def is_path_in_sandbox(path: Path | str, sandbox_root: Path | str | None = None) -> bool:
    sandbox = sandbox_root or get_sandbox_root() or Path('.').resolve()
    r = validate_path_sandbox(sandbox, path)
    return r.is_valid


def _extract_path_arguments(command: str, args: list[str]) -> list[str]:
    if not args:
        return []
    start = 0
    for i, a in enumerate(args):
        if a.startswith('-'):
            start = i + 1
        else:
            break
    remaining = args[start:]

    if command == 'find':
        res = []
        for a in remaining:
            if a.startswith('-'):
                break
            res.append(a)
        return res
    elif command in ('cat', 'head', 'tail', 'ls', 'less', 'more'):
        return remaining
    elif command in ('grep', 'rg', 'ripgrep'):
        res = []
        skip_next = False
        for a in remaining:
            if skip_next:
                skip_next = False
                continue
            if a.startswith('-'):
                if a in ('-e', '--regexp', '-f', '--file', '--include', '--exclude'):
                    skip_next = True
                continue
            res.append(a)
        return res
    elif command in ('wc', 'stat', 'du', 'df'):
        return remaining
    else:
        return [a for a in remaining if not a.startswith('-')]
