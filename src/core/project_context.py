"""Project Context - 管理项目级 .clawd 目录路径

核心设计理念:
- 当用户在某个项目目录下运行 clawd CLI 时，自动在该目录下创建 .clawd/ 文件夹
- 所有会话记录、记忆、数据库、缓存等资产都存储在该项目目录下
- 每个项目拥有独立的数据目录，互不干扰
- 支持通过 CLAWD_DIR 环境变量覆盖默认路径

目录结构:
    项目目录/
    └── .clawd/
        ├── sessions/            # 会话记录
        │   └── clawd.db         # SQLite 主数据库
        ├── memory/              # 多层记忆
        │   └── episodic/
        ├── brain/               # Brain 模块数据
        ├── checkpoints/         # Agent 检查点
        ├── experience/          # 经验库
        └── transcript.json      # 转录记录
"""
from __future__ import annotations

import os
from pathlib import Path


class ProjectContext:
    """项目上下文 - 管理项目级 .clawd 目录路径

    所有模块通过此类获取统一的存储路径，避免硬编码。
    支持通过环境变量 CLAWD_DIR 覆盖默认路径。

    用法:
        ctx = ProjectContext()  # 自动使用当前工作目录
        ctx = ProjectContext(workdir=Path('/path/to/project'))
        ctx.ensure_dirs()  # 自动创建 .clawd 目录结构
    """

    def __init__(self, workdir: Path | None = None) -> None:
        """初始化项目上下文

        Args:
            workdir: 项目工作目录，默认为当前工作目录 (Path.cwd())
        """
        self.workdir = workdir or Path.cwd()
        self._clawd_dir: Path | None = None

    def _resolve_clawd_dir(self) -> Path:
        """解析 .clawd 目录路径

        优先级:
        1. CLAWD_DIR 环境变量（绝对路径）
        2. workdir / .clawd

        Returns:
            .clawd 目录的绝对路径
        """
        env_dir = os.environ.get('CLAWD_DIR', '').strip()
        if env_dir:
            return Path(env_dir).resolve()
        return self.workdir.resolve() / '.clawd'

    @property
    def clawd_dir(self) -> Path:
        """.clawd 根目录"""
        if self._clawd_dir is None:
            self._clawd_dir = self._resolve_clawd_dir()
        return self._clawd_dir

    def ensure_dirs(self) -> None:
        """创建所有必需的子目录（幂等操作）"""
        dirs = [
            self.clawd_dir,
            self.sessions_dir,
            self.memory_dir,
            self.episodic_dir,
            self.brain_dir,
            self.checkpoints_dir,
            self.experience_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # 路径属性
    # =========================================================================

    @property
    def sessions_dir(self) -> Path:
        """会话存储目录"""
        return self.clawd_dir / 'sessions'

    @property
    def db_path(self) -> Path:
        """SQLite 数据库路径"""
        return self.sessions_dir / 'clawd.db'

    @property
    def memory_dir(self) -> Path:
        """记忆存储目录"""
        return self.clawd_dir / 'memory'

    @property
    def episodic_dir(self) -> Path:
        """情景记忆目录"""
        return self.memory_dir / 'episodic'

    @property
    def brain_dir(self) -> Path:
        """Brain 模块数据目录"""
        return self.clawd_dir / 'brain'

    @property
    def checkpoints_dir(self) -> Path:
        """Agent 检查点目录"""
        return self.clawd_dir / 'checkpoints'

    @property
    def experience_dir(self) -> Path:
        """经验库目录"""
        return self.clawd_dir / 'experience'

    @property
    def context_index_path(self) -> Path:
        """上下文索引文件路径 (汲取 GoalX)"""
        return self.clawd_dir / 'context_index.json'

    @property
    def quality_debt_path(self) -> Path:
        """质量债文件路径 (汲取 GoalX)"""
        return self.clawd_dir / 'quality_debt.json'

    @property
    def transcript_path(self) -> Path:
        """转录文件路径"""
        return self.clawd_dir / 'transcript.json'

    @property
    def readline_history_path(self) -> Path:
        """readline 历史文件路径"""
        return self.clawd_dir / 'readline_history'

    @property
    def evolution_path(self) -> Path:
        """进化状态文件路径"""
        return self.clawd_dir / 'evolution.json'

    @property
    def enterprise_ltm_path(self) -> Path:
        """企业级长期记忆数据库路径"""
        return self.clawd_dir / 'enterprise_ltm.db'

    # =========================================================================
    # 状态与诊断
    # =========================================================================

    @property
    def exists(self) -> bool:
        """检查 .clawd 目录是否已存在"""
        return self.clawd_dir.exists()

    def get_status(self) -> dict:
        """获取项目上下文状态摘要"""
        return {
            'workdir': str(self.workdir),
            'clawd_dir': str(self.clawd_dir),
            'exists': self.exists,
            'db_exists': self.db_path.exists(),
        }

    def __repr__(self) -> str:
        return f'ProjectContext(workdir={self.workdir!r}, clawd_dir={self.clawd_dir!r})'
