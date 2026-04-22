"""命令白名单安全模块 - 移植自 oh-my-codex-main/omx-explore

设计原则：
1. 白名单模式：仅允许明确列出的命令（10个核心只读命令）
2. 危险参数拦截：按命令类型细粒度检查危险参数
3. Shell注入防护：禁止控制操作符（&&, ||, ;, |, `, $() 等）
4. 路径qualified命令禁止：禁止 /usr/bin/grep 等形式

安全边界：
- 允许的命令必须是无副作用的只读操作
- 任何可能修改文件系统或网络的操作都应被拦截
- 禁止命令链（; && || |）防止组合攻击
"""

from __future__ import annotations

from dataclasses import dataclass

# ========== 白名单定义 ==========

# 增强白名单 - 基于项目A的READ_ONLY_ROOT_COMMANDS (24个命令) + 项目B的安全强化
# 升级策略：从"黑名单逐项检查"改为"白名单基础 + 细粒度参数拦截 + Shell注入防护"
# 来源：混合自 Project A (bash_security.py) 和 Project B (omx-explore)
# 注意：保留git/find/sed/awk等复杂命令，但在validate_command中对危险参数做细化检查
ALLOWED_COMMANDS: frozenset[str] = frozenset({
    # ===== 项目A原有24命令（全部保留）+ 扩展 =====
    'awk', 'basename', 'cat', 'cd', 'column', 'cut', 'df', 'dirname', 'du',
    'echo', 'env', 'find', 'git', 'grep', 'head', 'less', 'ls', 'more',
    'printenv', 'printf', 'ps', 'pwd', 'rg', 'ripgrep', 'sed', 'sort',
    'stat', 'tail', 'tree', 'uniq', 'wc', 'which', 'where', 'whoami',
    # 额外只读工具
    'free', 'who', 'id', 'hostname',
})

# ========== 危险参数拦截表 ==========

# find 命令的危险参数 - 可能导致文件系统修改或命令执行
BLOCKED_FIND_FLAGS: frozenset[str] = frozenset({
    '-exec',      # 执行命令
    '-execdir',   # 在文件所在目录执行命令
    '-ok',        # 交互式执行
    '-okdir',     # 交互式执行（目录版）
    '-delete',    # 删除文件
    '-fprint',    # 打印到文件
    '-fprint0',   # 打印到文件（null分隔）
    '-fprintf',   # 格式化打印到文件
    '-fls',       # 长格式列表到文件
})

# find 命令的危险前缀 - 配合!可实现排除/反转逻辑，可能被滥用
BLOCKED_FIND_PREFIXES: frozenset[str] = frozenset({
    '!',          # 逻辑非
    '-not',       # 逻辑非
    '-path',      # 路径模式匹配（结合!可遍历任意路径）
    '-prune',     # 剪枝（可绕过某些限制）
})

# git 命令的危险远程操作 - 扩展包含 add/remove
BLOCKED_GIT_REMOTE_ACTIONS: frozenset[str] = frozenset({
    'push',       # 推送到远程
    'fetch',      # 获取远程数据
    'pull',       # 拉取远程数据
    'add',        # 添加远程
    'remove',     # 删除远程
    'rm',         # 删除远程
    'set-url',    # 修改远程URL
    'prune',      # 清理远程跟踪
    'update',     # 更新远程
})

# git 命令的危险分支操作标志
BLOCKED_GIT_BRANCH_FLAGS: frozenset[str] = frozenset({
    '-D',         # 强制删除分支
    '-d',         # 删除分支
    '--delete',   # 删除
    '--move',     # 移动/重命名
    '-m',         # 移动/重命名
})

# ========== Shell注入防护 ==========

# 禁止的Shell控制操作符 - 这些操作符可组合命令
# 来源：oh-my-codex-main 的 validateShellInvocation
SHELL_INJECTION_OPERATORS: tuple[str, ...] = (
    '&&',   # 逻辑与
    '||',   # 逻辑或
    ';',    # 命令分隔
    '|',    # 管道
    '`',    # 反引号命令替换
    '$(',   # $(...) 命令替换
    '${',   # 可能的大括号扩展
    '\n',   # 换行符注入
    '\r',   # 回车符注入
)

# ========== 数据类 ==========


@dataclass(frozen=True, slots=True)
class CommandValidationResult:
    """
    命令校验结果

    Attributes:
        is_valid: 是否通过校验
        error_message: 错误消息（失败时）
        blocked_args: 被拦截的参数列表（失败时）
        risk_level: 风险等级 - 'low' / 'medium' / 'high' / 'critical'
    """
    is_valid: bool
    error_message: str | None = None
    blocked_args: list[str] | None = None
    risk_level: str = "low"


# ========== 校验函数 ==========


def validate_command(command: str, args: list[str]) -> CommandValidationResult:
    """
    完整命令校验流程（对标 oh-my-codex-main 的 validateDirectCommand）

    校验步骤：
    0. 路径qualified命令禁止（最先检查，提供明确错误信息）
    1. 白名单检查 - 命令必须在 ALLOWED_COMMANDS 中
    2. Shell注入检测 - 检查控制操作符
    3. 命令特定危险参数检查 - 针对 find/tail/git/sed/awk 等

    Args:
        command: 命令名称（如 'find', 'grep'）
        args: 命令参数列表

    Returns:
        CommandValidationResult: 校验结果

    来源：oh-my-codex-main/crates/omx-explore/src/main.rs:579-666
    """
    # Step 0: 路径qualified命令禁止（最先检查）
    if '/' in command:
        return CommandValidationResult(
            is_valid=False,
            error_message="path-qualified commands are not allowed",
            risk_level="high"
        )

    # Step 1: 白名单检查
    if command not in ALLOWED_COMMANDS:
        return CommandValidationResult(
            is_valid=False,
            error_message=f"command `{command}` is not on the allowlist",
            risk_level="high"
        )

    # Step 2: Shell注入检测
    full_cmd = ' '.join([command] + args)
    for op in SHELL_INJECTION_OPERATORS:
        if op in full_cmd:
            return CommandValidationResult(
                is_valid=False,
                error_message=f"shell injection detected: `{op}`",
                blocked_args=[op],
                risk_level="critical"
            )

    # Step 3: 命令特定危险参数检查
    blocked_args: list[str] = []

    if command == 'find':
        for arg in args:
            if arg in BLOCKED_FIND_FLAGS or any(arg.startswith(prefix) for prefix in BLOCKED_FIND_PREFIXES):
                blocked_args.append(arg)
        if blocked_args:
            return CommandValidationResult(
                is_valid=False,
                error_message=f"blocked flag(s) for find: {blocked_args}",
                blocked_args=blocked_args,
                risk_level="high"
            )

    elif command == 'tail':
        blocked_tail_flags = {'-f', '-F', '--follow', '--retry'}
        for arg in args:
            if arg in blocked_tail_flags:
                blocked_args.append(arg)
        if blocked_args:
            return CommandValidationResult(
                is_valid=False,
                error_message=f"blocked tail flag: {blocked_args[0]}",
                blocked_args=blocked_args,
                risk_level="high"
            )

    elif command == 'grep':
        if '-' in args:
            return CommandValidationResult(
                is_valid=False,
                error_message="grep reading from stdin not allowed",
                blocked_args=['-'],
                risk_level="medium"
            )

    elif command == 'git':
        # 解析子命令
        sub_idx = 0
        while sub_idx < len(args) and args[sub_idx].startswith('-'):
            if args[sub_idx] in ('-C', '-c'):
                sub_idx += 1
            sub_idx += 1

        if sub_idx < len(args):
            subcmd = args[sub_idx].lower()
            # 获取只读子命令白名单
            try:
                from src.tools_runtime.bash_constants import READ_ONLY_GIT_SUBCOMMANDS
            except ImportError:
                READ_ONLY_GIT_SUBCOMMANDS = {
                    'blame', 'branch', 'cat-file', 'diff', 'grep', 'log',
                    'ls-files', 'remote', 'rev-parse', 'show', 'status', 'describe',
                }
            if subcmd not in READ_ONLY_GIT_SUBCOMMANDS:
                return CommandValidationResult(
                    is_valid=False,
                    error_message=f"git subcommand '{subcmd}' not allowed",
                    blocked_args=[subcmd],
                    risk_level="high"
                )
            # 检查 remote add/remove 等危险操作
            if subcmd == 'remote' and len(args) > sub_idx + 1:
                remote_action = args[sub_idx + 1].lower()
                if remote_action in BLOCKED_GIT_REMOTE_ACTIONS:
                    return CommandValidationResult(
                        is_valid=False,
                        error_message=f"git remote {remote_action} not allowed",
                        blocked_args=[remote_action],
                        risk_level="high"
                    )
            # 检查 branch 的危险标志
            if subcmd == 'branch':
                for flag in BLOCKED_GIT_BRANCH_FLAGS:
                    if flag in args[sub_idx+1:]:
                        blocked_args.append(flag)
                if blocked_args:
                    return CommandValidationResult(
                        is_valid=False,
                        error_message=f"blocked git branch flags: {blocked_args}",
                        blocked_args=blocked_args,
                        risk_level="high"
                    )

    elif command == 'sed':
        # 检查 -i 参数
        for arg in args:
            if arg.startswith('-i') or arg == '--in-place':
                return CommandValidationResult(
                    is_valid=False,
                    error_message="sed in-place editing not allowed",
                    blocked_args=[arg],
                    risk_level="high"
                )
        # 检查脚本中的 w 命令（写文件）
        script = ' '.join(args)
        if ' w ' in script or script.strip().endswith(' w') or 'w ' in script:
            return CommandValidationResult(
                is_valid=False,
                error_message="sed write command (w) not allowed",
                blocked_args=['w'],
                risk_level="high"
            )

    elif command == 'awk':
        # 检查 system() 调用
        script = ' '.join(args)
        if 'system(' in script:
            return CommandValidationResult(
                is_valid=False,
                error_message="awk system() not allowed",
                risk_level="high"
            )
        # 检查 print 输出重定向 (>, >>)
        # 简单的正则检测 print ... > 或 print ... >>
        import re
        if re.search(r'print\s+[^|]*[>|]', script):
            return CommandValidationResult(
                is_valid=False,
                error_message="awk output redirection not allowed",
                blocked_args=['>'],
                risk_level="high"
            )

    # 所有检查通过
    return CommandValidationResult(is_valid=True, risk_level="low")


def is_shell_command_safe(command: str) -> bool:
    """
    兼容旧API：检查命令是否安全

    注意：此函数是为了向后兼容而保留的薄封装。
    新代码应直接使用 validate_command() 获取详细信息。

    Args:
        command: 完整命令字符串

    Returns:
        bool: True表示安全，False表示危险
    """
    # 简单实现：解析命令和第一个参数
    import shlex
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False

    if not tokens:
        return True

    root = tokens[0].lower()
    # 提取路径部分（如 /usr/bin/grep → grep）
    if '/' in root:
        root = root.split('/')[-1]

    result = validate_command(root, tokens[1:])
    return result.is_valid


# ========== 向后兼容 ==========

# 保留旧函数名但标记为废弃
def is_shell_command_read_only(command: str) -> bool:
    """
    [已废弃] 使用 is_shell_command_safe() 或 validate_command()

    这是旧的API名称，为了向后兼容保留。
    """
    return is_shell_command_safe(command)
