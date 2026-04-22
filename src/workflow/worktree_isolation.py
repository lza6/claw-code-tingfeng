"""
Git Worktree 隔离执行模块

从 oh-my-codex-main/src/team/worktree.ts 汲取的设计。
用于为多智能体并行执行提供 Git worktree 隔离,避免并发写入冲突。

核心功能:
- 为每个 Worker 创建独立的 Git worktree
- 支持 detached HEAD 模式和分支跟踪
- 自动回滚机制 (rollback_provisioned_worktrees)
- 领导者工作区清洁断言
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorktreeMode:
    """Worktree 模式配置"""
    enabled: bool = False
    detached: bool = True
    name: str | None = None


@dataclass
class PlannedWorktreeTarget:
    """计划的 Worktree 目标"""
    repo_root: str
    worktree_path: str
    detached: bool
    base_ref: str
    branch_name: str | None = None


@dataclass
class EnsureWorktreeResult:
    """确保 Worktree 的结果"""
    repo_root: str
    worktree_path: str
    detached: bool
    branch_name: str | None = None
    created: bool = False
    reused: bool = False
    created_branch: bool = False


def _run_git(args: list[str], cwd: str, check: bool = True) -> tuple[int, str, str]:
    """运行 Git 命令并返回 (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(
            ['git'] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=30
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Git command timed out: git {' '.join(args)}")


def is_git_repository(cwd: str) -> bool:
    """检查目录是否为 Git 仓库"""
    rc, _, _ = _run_git(['rev-parse', '--show-toplevel'], cwd, check=False)
    return rc == 0


def sanitize_path_token(value: str) -> str:
    """将字符串转换为路径安全的 token"""
    normalized = re.sub(r'[^a-z0-9]+', '-', value.lower())
    normalized = re.sub(r'-+', '-', normalized)
    normalized = normalized.strip('-')
    return normalized or 'default'


def validate_branch_name(repo_root: str, branch_name: str) -> None:
    """验证分支名称是否合法"""
    rc, _, stderr = _run_git(
        ['check-ref-format', '--branch', branch_name],
        repo_root,
        check=False
    )
    if rc != 0:
        raise ValueError(f"Invalid branch name '{branch_name}': {stderr}")


def branch_exists(repo_root: str, branch_name: str) -> bool:
    """检查分支是否存在"""
    rc, _, _ = _run_git(
        ['show-ref', '--verify', '--quiet', f'refs/heads/{branch_name}'],
        repo_root,
        check=False
    )
    return rc == 0


def is_worktree_dirty(worktree_path: str) -> bool:
    """检查 worktree 是否有未提交的更改"""
    rc, stdout, stderr = _run_git(
        ['status', '--porcelain'],
        worktree_path,
        check=False
    )
    if rc != 0:
        raise RuntimeError(f"Failed to check worktree status: {stderr}")
    return bool(stdout.strip())


def read_workspace_status_lines(cwd: str) -> list[str]:
    """读取工作区状态行 (git status --porcelain)"""
    rc, stdout, stderr = _run_git(
        ['status', '--porcelain', '--untracked-files=all'],
        cwd,
        check=False
    )
    if rc != 0:
        raise RuntimeError(f"Failed to read workspace status: {stderr}")
    return [line for line in stdout.split('\n') if line.strip()]


def assert_clean_leader_workspace_for_worker_worktrees(cwd: str) -> None:
    """
    断言领导者工作区是干净的,才能创建 worker worktrees

    这是防止并发冲突的关键安全检查。
    """
    lines = read_workspace_status_lines(cwd)
    if not lines:
        return

    preview = ' | '.join(lines[:8])
    raise RuntimeError(
        f"Leader workspace is dirty. Cannot create worker worktrees.\n"
        f"Preview: {preview}\n"
        f"Please commit or stash changes before starting parallel execution."
    )


def list_worktrees(repo_root: str) -> list[dict]:
    """列出所有 worktrees"""
    rc, stdout, stderr = _run_git(
        ['worktree', 'list', '--porcelain'],
        repo_root,
        check=False
    )
    if rc != 0:
        raise RuntimeError(f"Failed to list worktrees: {stderr}")

    if not stdout.strip():
        return []

    entries = []
    chunks = [chunk.strip() for chunk in stdout.split('\n\n') if chunk.strip()]

    for chunk in chunks:
        lines = [line.strip() for line in chunk.split('\n') if line.strip()]
        worktree_line = next((l for l in lines if l.startswith('worktree ')), None)
        head_line = next((l for l in lines if l.startswith('HEAD ')), None)
        branch_line = next((l for l in lines if l.startswith('branch ')), None)

        if not worktree_line or not head_line:
            continue

        entries.append({
            'path': str(Path(worktree_line[len('worktree '):]).resolve()),
            'head': head_line[len('HEAD '):].strip(),
            'branch_ref': branch_line[len('branch '):].strip() if branch_line else None,
            'detached': 'detached' in lines or not branch_line,
        })

    return entries


def find_worktree_by_path(entries: list[dict], worktree_path: str) -> dict | None:
    """通过路径查找 worktree"""
    resolved = str(Path(worktree_path).resolve())
    return next((e for e in entries if e['path'] == resolved), None)


def has_branch_in_use(entries: list[dict], branch_name: str, worktree_path: str) -> bool:
    """检查分支是否在其他 worktree 中被使用"""
    expected_ref = f'refs/heads/{branch_name}'
    resolved_path = str(Path(worktree_path).resolve())
    return any(
        e['branch_ref'] == expected_ref and e['path'] != resolved_path
        for e in entries
    )


def resolve_worktree_path(
    repo_root: str,
    scope: str,
    mode_name: str | None = None,
    team_name: str | None = None,
    worker_name: str | None = None,
    worktree_tag: str | None = None,
) -> str:
    """
    解析 worktree 路径

    Args:
        repo_root: Git 仓库根目录
        scope: 作用域 ('launch', 'team', 'autoresearch')
        mode_name: 模式名称
        team_name: 团队名称
        worker_name: Worker 名称
        worktree_tag: Worktree 标签

    Returns:
        Worktree 的绝对路径
    """
    repo_path = Path(repo_root)
    parent = repo_path.parent
    bucket = f"{repo_path.name}.clawd-worktrees"

    if scope == 'launch':
        if not mode_name:
            return str(parent / bucket / 'launch-detached')
        return str(parent / bucket / f"launch-{sanitize_path_token(mode_name)}")

    if scope == 'autoresearch':
        run_tag = sanitize_path_token(worktree_tag or 'run')
        safe_mode = sanitize_path_token(mode_name or 'default')
        return str(repo_path / '.clawd' / 'worktrees' / f"autoresearch-{safe_mode}-{run_tag}")

    # Team scope
    team_name = sanitize_path_token(team_name or 'team')
    worker_name = sanitize_path_token(worker_name or 'worker')
    return str(repo_path / '.clawd' / 'team' / team_name / 'worktrees' / worker_name)


def plan_worktree_target(
    cwd: str,
    scope: str = 'team',
    mode: WorktreeMode | None = None,
    team_name: str | None = None,
    worker_name: str | None = None,
    worktree_tag: str | None = None,
) -> PlannedWorktreeTarget | None:
    """
    规划 worktree 目标

    Args:
        cwd: 当前工作目录
        scope: 作用域
        mode: Worktree 模式配置
        team_name: 团队名称
        worker_name: Worker 名称
        worktree_tag: Worktree 标签

    Returns:
        计划的目标,如果 worktree 未启用则返回 None
    """
    if not mode or not mode.enabled:
        return None

    # 获取仓库根目录和基础引用
    rc, repo_root, stderr = _run_git(['rev-parse', '--show-toplevel'], cwd)
    if rc != 0:
        raise RuntimeError(f"Not a git repository: {stderr}")

    rc, base_ref, stderr = _run_git(['rev-parse', 'HEAD'], repo_root)
    if rc != 0:
        raise RuntimeError(f"Failed to get HEAD ref: {stderr}")

    # 确定分支名称
    branch_name = None
    if mode.enabled and not mode.detached and mode.name:
        if scope == 'launch':
            branch_name = mode.name
        elif scope == 'autoresearch':
            run_tag = sanitize_path_token(worktree_tag or 'run')
            branch_name = f"autoresearch/{sanitize_path_token(mode.name)}/{run_tag}"
        elif scope == 'team':
            if not worker_name:
                raise ValueError("Worker name is required for team worktree")
            branch_name = f"{mode.name}/{worker_name}"

        if branch_name:
            validate_branch_name(repo_root, branch_name)

    # 解析 worktree 路径
    worktree_path = resolve_worktree_path(
        repo_root,
        scope,
        mode_name=mode.name,
        team_name=team_name,
        worker_name=worker_name,
        worktree_tag=worktree_tag,
    )

    return PlannedWorktreeTarget(
        repo_root=repo_root,
        worktree_path=worktree_path,
        detached=mode.detached,
        base_ref=base_ref,
        branch_name=branch_name,
    )


def ensure_worktree(plan: PlannedWorktreeTarget | None) -> EnsureWorktreeResult | None:
    """
    确保 worktree 存在,如果不存在则创建

    Args:
        plan: 计划的目标

    Returns:
        结果,如果 worktree 未启用则返回 None
    """
    if not plan:
        return None

    # 列出所有现有的 worktrees
    all_worktrees = list_worktrees(plan.repo_root)
    existing = find_worktree_by_path(all_worktrees, plan.worktree_path)

    expected_branch_ref = f'refs/heads/{plan.branch_name}' if plan.branch_name else None

    # 检查现有 worktree 是否匹配
    if existing:
        if plan.detached:
            if not existing['detached'] or existing['head'] != plan.base_ref:
                raise RuntimeError(
                    f"Worktree target mismatch at {plan.worktree_path}: "
                    f"expected detached @ {plan.base_ref}, "
                    f"got {'attached' if not existing['detached'] else existing['head']}"
                )
        else:
            if existing['branch_ref'] != expected_branch_ref:
                raise RuntimeError(
                    f"Worktree target mismatch at {plan.worktree_path}: "
                    f"expected branch {expected_branch_ref}, "
                    f"got {existing['branch_ref']}"
                )

        # 检查是否干净
        if is_worktree_dirty(plan.worktree_path):
            raise RuntimeError(
                f"Worktree is dirty: {plan.worktree_path}\n"
                f"Please commit or stash changes before reusing."
            )

        return EnsureWorktreeResult(
            repo_root=plan.repo_root,
            worktree_path=str(Path(plan.worktree_path).resolve()),
            detached=plan.detached,
            branch_name=plan.branch_name,
            created=False,
            reused=True,
            created_branch=False,
        )

    # 检查路径是否存在但不是 worktree
    worktree_path_obj = Path(plan.worktree_path)
    if worktree_path_obj.exists():
        raise RuntimeError(
            f"Path exists but is not a worktree: {plan.worktree_path}\n"
            f"Please remove it manually or choose a different path."
        )

    # 检查分支是否在其他 worktree 中被使用
    if plan.branch_name and has_branch_in_use(all_worktrees, plan.branch_name, plan.worktree_path):
        raise RuntimeError(
            f"Branch '{plan.branch_name}' is already checked out in another worktree.\n"
            f"Use a different branch name or remove the other worktree first."
        )

    # 创建父目录
    worktree_path_obj.parent.mkdir(parents=True, exist_ok=True)

    # 检查分支是否已存在
    branch_already_existed = False
    if plan.branch_name:
        branch_already_existed = branch_exists(plan.repo_root, plan.branch_name)

    # 构建 git worktree add 命令
    add_args = ['worktree', 'add']
    if plan.detached:
        add_args.extend(['--detach', plan.worktree_path, plan.base_ref])
    elif branch_already_existed:
        add_args.extend([plan.worktree_path, plan.branch_name])
    else:
        add_args.extend(['-b', plan.branch_name, plan.worktree_path, plan.base_ref])

    rc, stdout, stderr = _run_git(add_args, plan.repo_root, check=False)
    if rc != 0:
        # 检查是否是分支被使用的错误
        if plan.branch_name and re.search(
            r'already checked out|already used by worktree|is already checked out',
            stderr,
            re.IGNORECASE
        ):
            raise RuntimeError(
                f"Branch '{plan.branch_name}' is already in use by another worktree."
            )
        raise RuntimeError(f"Failed to create worktree: {stderr}")

    return EnsureWorktreeResult(
        repo_root=plan.repo_root,
        worktree_path=str(Path(plan.worktree_path).resolve()),
        detached=plan.detached,
        branch_name=plan.branch_name,
        created=True,
        reused=False,
        created_branch=bool(plan.branch_name and not branch_already_existed),
    )


async def rollback_provisioned_worktrees(
    results: list[EnsureWorktreeResult | None],
    skip_branch_deletion: bool = False,
) -> None:
    """
    回滚已创建的 worktrees

    在任务失败或取消时清理临时 worktrees。

    Args:
        results: ensure_worktree 返回的结果列表
        skip_branch_deletion: 是否跳过分支删除 (RALPH 策略)
    """
    # 只处理新创建的 worktrees,按逆序回滚
    created = [r for r in reversed(results) if r and r.created]
    errors = []

    for result in created:
        try:
            # 移除 worktree
            _run_git(
                ['worktree', 'remove', '--force', result.worktree_path],
                result.repo_root,
                check=False
            )
        except Exception as e:
            errors.append(f"remove:{result.worktree_path}:{e!s}")
            continue

        # 如果跳过了分支删除,继续下一个
        if skip_branch_deletion:
            continue
        if not result.created_branch or not result.branch_name:
            continue

        # 检查分支是否还在其他 worktree 中被使用
        entries_after_remove = list_worktrees(result.repo_root)
        still_checked_out = has_branch_in_use(
            entries_after_remove,
            result.branch_name,
            result.worktree_path
        )
        if still_checked_out:
            continue

        # 删除分支
        try:
            _run_git(
                ['branch', '-D', result.branch_name],
                result.repo_root,
                check=False
            )
        except Exception as e:
            # 只有当分支仍然存在时才记录错误
            if branch_exists(result.repo_root, result.branch_name):
                errors.append(f"delete_branch:{result.branch_name}:{e!s}")

    if errors:
        raise RuntimeError(f"Worktree rollback failed: {' | '.join(errors)}")


# ===== 便捷函数 =====

def create_team_worker_worktree(
    cwd: str,
    team_name: str,
    worker_name: str,
    mode_name: str | None = None,
) -> EnsureWorktreeResult | None:
    """
    为团队 Worker 创建 worktree 的便捷函数

    Args:
        cwd: 当前工作目录
        team_name: 团队名称
        worker_name: Worker 名称
        mode_name: 模式名称 (可选,默认使用 worker_name)

    Returns:
        结果或 None
    """
    mode = WorktreeMode(
        enabled=True,
        detached=False,
        name=mode_name or worker_name,
    )

    plan = plan_worktree_target(
        cwd,
        scope='team',
        mode=mode,
        team_name=team_name,
        worker_name=worker_name,
    )

    return ensure_worktree(plan)


# ===== Worker Shutdown 合并报告（借鉴 oh-my-codex）=====

@dataclass
class WorkerShutdownMergeReport:
    """
    Worker 关闭时的合并结果报告
    
    记录每个 Worker 的变更如何合并到 Leader workspace。
    支持四种合并状态：merged, conflict, noop, skipped
    """
    worker_name: str
    merge_result: str  # merged / conflict / noop / skipped
    commit_sha: str | None = None  # 如果成功合并，记录 commit SHA
    conflict_files: list[str] = field(default_factory=list)  # 冲突文件列表
    message: str = ""  # 附加说明消息

    @property
    def is_success(self) -> bool:
        """检查合并是否成功"""
        return self.merge_result in ('merged', 'noop')


def create_merge_report(
    worker_name: str,
    merge_result: str,
    commit_sha: str | None = None,
    conflict_files: list[str] | None = None,
    message: str = "",
) -> WorkerShutdownMergeReport:
    """
    创建合并报告的便捷函数
    
    Args:
        worker_name: Worker 名称
        merge_result: 合并结果 (merged/conflict/noop/skipped)
        commit_sha: 合并后的 commit SHA
        conflict_files: 冲突文件列表
        message: 附加说明
        
    Returns:
        WorkerShutdownMergeReport 实例
    """
    return WorkerShutdownMergeReport(
        worker_name=worker_name,
        merge_result=merge_result,
        commit_sha=commit_sha,
        conflict_files=conflict_files or [],
        message=message,
    )


# ===== 导出 =====
__all__ = [
    "EnsureWorktreeResult",
    "PlannedWorktreeTarget",
    "WorkerShutdownMergeReport",
    "WorktreeMode",
    "assert_clean_leader_workspace_for_worker_worktrees",
    "create_merge_report",
    "create_team_worker_worktree",
    "ensure_worktree",
    "is_git_repository",
    "plan_worktree_target",
    "rollback_provisioned_worktrees",
]
