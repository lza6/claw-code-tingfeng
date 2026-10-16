"""共享路径解析工具 - 防止路径遍历攻击与敏感文件读取"""
from __future__ import annotations

from pathlib import Path

# 敏感文件/目录防护。
# src/utils/path_security.py 里早已实现 is_sensitive_file 与 FORBIDDEN_DIRS，
# 但从未被任何工具接线 —— 结果是 Agent 可以直接读 `.env`，把明文 API Key
# 读进会话、再作为上下文发给远端 LLM。这里在**唯一的统一入口**接入，
# 使 FileReadTool / FileEditTool / GlobTool / GrepTool 同时获得防护。
_SENSITIVE_MARKERS: tuple[str, ...] = (
    '.env', 'id_rsa', 'id_ed25519', '.pem', '.key',
    'credentials.json', 'secrets.yaml', 'secrets.json',
    'passwd', 'shadow',
)

_FORBIDDEN_DIR_PARTS: frozenset[str] = frozenset({
    '.git', '.svn', '.hg', 'CVS', '__pycache__', 'node_modules',
    '.venv', 'venv', 'env', '.clawd',
})


# 允许读取的 .env 变体：模板文件不含真实密钥，且是引导新用户
# 配置环境的必需材料。只放行这一种，其余 .env.* 一律拒绝。
_SENSITIVE_ALLOWLIST: frozenset[str] = frozenset({
    '.env.example', '.env.sample', '.env.template',
})


def is_sensitive_path(path: Path) -> bool:
    """判断路径是否指向敏感文件或受保护目录。

    两份判据：
    1. 文件名包含敏感标记（`.env`、`id_rsa`、`.pem`、`.key` …）
       —— 用包含而非相等，以覆盖 `.env.local` / `.env.production` 等变体。
       `.env.example` 一类纯模板文件显式豁免：它们本来就是要给人看、
       用于引导配置的，不含真实凭据。
    2. 路径中任一层目录名命中 FORBIDDEN_DIRS。
       其中 `.clawd` 尤其关键：它在 `.gitignore` 里受保护，但那是防 git，
       不防 Agent；而 `provider.json`（明文 apiKey）正写在里面。
    """
    name = path.name.lower()
    if name in _SENSITIVE_ALLOWLIST:
        return False
    if any(marker in name for marker in _SENSITIVE_MARKERS):
        return True
    return any(part in _FORBIDDEN_DIR_PARTS for part in path.parts)


def resolve_path(
    file_path: str,
    base_path: Path,
) -> Path | None:
    """解析文件路径，防止路径遍历攻击与敏感文件访问

    参数:
        file_path: 请求的文件路径
        base_path: 基准路径（不允许超出此目录）

    返回:
        解析后的 Path 对象，如果路径不安全/敏感则返回 None
    """
    path = Path(file_path)

    # 如果是相对路径，基于 base_path 解析
    if not path.is_absolute():
        path = base_path / path

    # 解析并检查是否仍在 base_path 下
    try:
        resolved = path.resolve()
        base_resolved = base_path.resolve()
        if not resolved.is_relative_to(base_resolved):
            return None
        # 敏感文件 / 受保护目录：即使在 base_path 内也拒绝
        if is_sensitive_path(resolved):
            return None
        return resolved
    except (ValueError, OSError):
        return None


# 二进制文件扩展名（禁止读取）- 统一常量
BINARY_EXTENSIONS: frozenset[str] = frozenset({
    '.pyc', '.pyo', '.so', '.dll', '.dylib', '.exe', '.bin',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.webp', '.tiff',
    '.zip', '.tar', '.gz', '.rar', '.7z', '.bz2', '.xz',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
})

# 支持读取的文本文件扩展名 - 统一常量
#
# 注意: 这里的白名单只表达"是不是文本文件"，不代表"允许读取"。
# 是否放行由 resolve_path() 的敏感路径判定决定。
TEXT_EXTENSIONS: frozenset[str] = frozenset({
    '.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.yaml', '.yml', '.toml',
    '.ini', '.cfg', '.conf', '.txt', '.md', '.rst', '.html', '.css', '.scss',
    '.xml', '.csv', '.log', '.sh', '.bat', '.ps1', '.gitignore',
    '.dockerignore', '.dockerfile', '.c', '.cpp', '.h', '.hpp', '.java',
    '.go', '.rs', '.rb', '.php', '.sql', '.graphql', '.proto',
})
