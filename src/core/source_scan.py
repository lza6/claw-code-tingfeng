"""源码文件扫描（带排除规则 + 上限）—— 别把 site-packages 当项目代码索引

真实事故：桌面端打包版把 Host 的 cwd 设成 `resources/host`，里面有内嵌 Python 运行时，
`world_model.initialize()` 用 `root.glob("**/*.py")` 扫到 **11,606 个 .py**（绝大多数是
site-packages），于是后台索引把事件循环与 CPU 占满，UI 打开「用量统计」一直卡在"加载中…"。

规则：
- 目录名命中 `EXCLUDED_DIR_PARTS`（site-packages / Lib / node_modules / venv / dist/…）整棵跳过；
- 以 `.` 开头的目录（.git/.clawd/…）与 `__pycache__` 跳过；
- 结果超过 `max_files` 时**不截断**，而是返回超限标记，由调用方决定"跳过索引并如实告知"
  （静默截断会让人以为索引完整，比不索引更糟）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: 这些目录一定不是"项目源码"（依赖/运行时/构建产物）
EXCLUDED_DIR_PARTS: frozenset[str] = frozenset({
    "site-packages", "dist-packages", "node_modules", "venv", ".venv", "env",
    "Lib", "lib", "include", "Scripts", "bin", "obj", "__pycache__",
    "dist", "build", "out", "target", ".git", ".clawd", ".next", ".cache",
    "graft", "coverage", "htmlcov", ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

#: 单次扫描默认上限（超过就不做全量索引）
DEFAULT_MAX_FILES = 5000


@dataclass(frozen=True)
class ScanResult:
    files: list[Path]
    truncated: bool          # 是否超过上限（此时 files 只保留前 max_files 个，仅供降级提示用）
    scanned_dirs: int = 0

    @property
    def count(self) -> int:
        return len(self.files)


def _is_excluded(rel_parts: tuple[str, ...]) -> bool:
    for part in rel_parts:
        if not part:
            continue
        if part.startswith(".") and part not in (".",):
            return True
        if part in EXCLUDED_DIR_PARTS:
            return True
    return False


def scan_source_files(
    root: Path | str,
    suffixes: tuple[str, ...] = (".py",),
    max_files: int = DEFAULT_MAX_FILES,
) -> ScanResult:
    """按排除规则扫描源码文件；超过 max_files 时 truncated=True"""
    base = Path(root)
    out: list[Path] = []
    truncated = False
    dirs = 0
    try:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel_parts = path.relative_to(base).parts[:-1]
            except ValueError:
                continue
            if _is_excluded(rel_parts):
                continue
            if not path.name.endswith(suffixes):
                continue
            out.append(path)
            if len(out) > max_files:
                truncated = True
                break
        dirs = 1
    except OSError as e:
        logger.warning(f"扫描源码目录失败 {base}: {e}")
    if truncated:
        logger.warning(
            f"源码文件数超过上限 {max_files}（{base}），本次不做全量索引；"
            f"可调大 CLAWD_WM_MAX_FILES 或确认排除规则是否匹配你的目录结构"
        )
        return ScanResult(files=out[:max_files], truncated=True, scanned_dirs=dirs)
    return ScanResult(files=out, truncated=False, scanned_dirs=dirs)


__all__ = [
    "DEFAULT_MAX_FILES",
    "EXCLUDED_DIR_PARTS",
    "ScanResult",
    "scan_source_files",
]
