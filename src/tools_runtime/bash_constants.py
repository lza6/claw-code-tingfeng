"""Bash Tool 常量和配置

定义危险命令模式、工作目录限制等安全常量。
"""
from __future__ import annotations

from pathlib import Path

# 危险命令模式 (Unix)
# 注意: 由于使用 shlex.split + 参数列表执行（无 shell=True），
# 命令注入攻击已被消除。此处仅保留真正的危险操作防护。
DANGEROUS_PATTERNS_UNIX = [
    r'\brm\s+(-rf?|--no-preserve-root)\b',  # rm -rf / 危险删除
    r'\bmkfs\b',  # 格式化文件系统
    r'\bdd\s',  # dd 命令（磁盘写入）
    r'>\s*/dev/sd',  # 写入磁盘设备
    r'\bsudo\s+reboot\b',  # 重启系统
    r'\bsudo\s+shutdown\b',  # 关机
    r':\(\)\{\s*:\|:\s*&\s*\}\s*;',  # fork bomb
    r'\b(?:curl|wget|fetch)\s+.*\|\s*(?:sh|bash)',  # 管道执行远程脚本
    r'\bsudo\s+-S\b',  # sudo 从标准输入读取密码
    r'\bchmod\s+[0-7]*7[0-7][0-7]\b',  # 危险权限设置（如 777）
    r'\bchown\s',  # 修改文件所有者
]

# 危险命令模式 (Windows)
# 注意: 由于使用参数列表执行（无 shell=True），命令注入已消除。
DANGEROUS_PATTERNS_WINDOWS = [
    r'\bdel\s+/[fqs]',  # 强制删除
    r'\bformat\s',  # 格式化磁盘
    r'\bchkdsk\s+/[fr]',  # 磁盘检查修复
    r'\bfsutil\s',  # 文件系统工具
    r'\bbcdedit\b',  # 启动配置编辑
    r'\breg\s+delete\b',  # 注册表删除
    r'\bpowershell\s+.*-[eE]ncodedCommand\b',  # Base64 编码命令
    r'\bwmic\s+.*delete\b',  # WMI 删除
    r'\bshutdown\s+/[rs]',  # 关机/重启
]

# 向后兼容别名
DANGEROUS_PATTERNS = DANGEROUS_PATTERNS_UNIX

# 允许的工作目录（防止路径逃逸）
# 默认允许当前工作目录及其子目录
_ALLOWED_WORKDIRS: list[Path] = []


def set_allowed_workdirs(workdirs: list[Path]) -> None:
    """设置允许的工作目录列表"""
    global _ALLOWED_WORKDIRS
    _ALLOWED_WORKDIRS = [w.resolve() for w in workdirs]


def get_allowed_workdirs() -> list[Path]:
    """获取允许的工作目录列表"""
    return _ALLOWED_WORKDIRS.copy()


# 自动初始化为当前工作目录
_ALLOWED_WORKDIRS = [Path.cwd()]


# Windows 内置命令列表（需要通过 cmd.exe /c 执行）
_WINDOWS_BUILTIN_COMMANDS = frozenset({
    'dir', 'cd', 'echo', 'type', 'set', 'cls', 'ver', 'time', 'date',
    'pause', 'vol', 'prompt', 'title', 'assoc', 'ftype', 'color',
    'pushd', 'popd', 'mklink', 'start', 'call', 'exit', 'goto',
    'for', 'if', 'rem', 'shift', 'endlocal', 'setlocal',
})

# Windows cmd.exe 危险字符（可能导致命令注入）
_WINDOWS_DANGEROUS_CHARS = frozenset({
    '&', '|', '&&', '||', '^', '`',  # 命令连接符和转义符
    '(', ')', '%', '!',  # 变量扩展
    '<', '>',  # 重定向
})
