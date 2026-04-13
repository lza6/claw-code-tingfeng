"""共享路径解析工具 - 防止路径遍历攻击"""
from __future__ import annotations

from pathlib import Path


def resolve_path(
    file_path: str,
    base_path: Path,
) -> Path | None:
    """解析文件路径，防止路径遍历攻击

    参数:
        file_path: 请求的文件路径
        base_path: 基准路径（不允许超出此目录）

    返回:
        解析后的 Path 对象，如果路径不安全则返回 None
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
TEXT_EXTENSIONS: frozenset[str] = frozenset({
    '.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.yaml', '.yml', '.toml',
    '.ini', '.cfg', '.conf', '.txt', '.md', '.rst', '.html', '.css', '.scss',
    '.xml', '.csv', '.log', '.sh', '.bat', '.ps1', '.env', '.gitignore',
    '.dockerignore', '.dockerfile', '.c', '.cpp', '.h', '.hpp', '.java',
    '.go', '.rs', '.rb', '.php', '.sql', '.graphql', '.proto',
})
