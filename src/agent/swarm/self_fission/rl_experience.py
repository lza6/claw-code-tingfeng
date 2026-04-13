"""RL-Experience Hub — 强化学习经验回传模块

核心功能:
- 任务经验记录: 记录每次任务的执行结果、成功/失败模式
- 历史最优方案检索: 基于语义相似度查找历史成功解决方案
- 高频失败模式预警: 识别并警告历史上经常失败的任务模式
- 跨任务自学: 在规划新任务时自动检索历史经验

存储:
- SQLite 持久化存储 (项目目录/.clawd/rl_experience.db)
- 支持向量相似检索 (TF-IDF + Cosine Similarity)

用法:
    from src.agent.swarm.rl_experience import RLExperienceHub

    hub = RLExperienceHub()

    # 记录任务经验
    hub.record_task_experience(
        task_description="实现 JWT 认证",
        solution="使用 PyJWT 库，生成 token 并验证签名",
        success=True,
        error_pattern=None,
        tags=["auth", "jwt", "security"],
    )

    # 检索历史最优方案
    best_practices = hub.find_best_practices("用户认证", top_k=3)

    # 检查高频失败模式
    warnings = hub.get_failure_warnings("加密功能")
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# 数据模型
# ============================================================================


@dataclass
class TaskExperience:
    """任务经验记录"""
    id: str = ""                          # 唯一 ID (基于内容哈希)
    task_description: str = ""            # 任务描述
    solution: str = ""                    # 解决方案
    success: bool = True                  # 是否成功
    error_pattern: str = ""               # 失败时的错误模式
    tags: list[str] = field(default_factory=list)  # 标签
    execution_time_seconds: float = 0.0   # 执行耗时
    created_at: float = field(default_factory=time.time)
    success_count: int = 1                # 成功次数
    failure_count: int = 0                # 失败次数
    embedding: dict[str, float] = field(default_factory=dict)  # 文本嵌入向量

    @property
    def success_rate(self) -> float:
        """计算成功率"""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.5
        return self.success_count / total

    @property
    def total_attempts(self) -> int:
        """总尝试次数"""
        return self.success_count + self.failure_count

    def generate_id(self) -> str:
        """基于内容生成 ID"""
        content = f"{self.task_description[:100]}:{self.solution[:50]}"
        self.id = "exp_" + hashlib.md5(content.encode()).hexdigest()[:12]
        return self.id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskExperience:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class FailurePattern:
    """失败模式记录"""
    pattern: str                        # 失败模式描述
    frequency: int = 1                  # 出现频率
    last_seen: float = field(default_factory=time.time)
    related_tags: list[str] = field(default_factory=list)
    example_error: str = ""


# ============================================================================
# TF-IDF 嵌入器
# ============================================================================


class ExperienceEmbedder:
    """轻量 TF-IDF 嵌入器 (无外部依赖)"""

    # 常见技术关键词
    TECH_KEYWORDS = {
        'auth', 'jwt', 'token', 'login', 'password', 'hash', 'encrypt',
        'api', 'rest', 'graphql', 'endpoint', 'route', 'handler',
        'database', 'sql', 'query', 'migration', 'schema', 'model',
        'css', 'style', 'component', 'ui', 'render', 'layout',
        'async', 'await', 'concurrent', 'thread', 'process',
        'test', 'unit', 'integration', 'mock', 'fixture',
        'cache', 'redis', 'memory', 'performance', 'optimize',
        'security', 'vulnerability', 'injection', 'xss', 'csrf',
        'docker', 'deploy', 'ci', 'cd', 'pipeline',
    }

    def __init__(self) -> None:
        self._idf: dict[str, float] = {}
        self._documents: list[str] = []
        self._built = False

    def fit(self, documents: list[str]) -> None:
        """构建 IDF 词汇表"""
        self._documents = documents
        doc_freq: dict[str, int] = {}

        for doc in documents:
            terms = set(self._tokenize(doc))
            for term in terms:
                doc_freq[term] = doc_freq.get(term, 0) + 1

        N = len(documents)
        self._idf = {
            term: math.log((N + 1) / (df + 1) + 1)
            for term, df in doc_freq.items()
        }
        self._built = True

    def embed(self, text: str) -> dict[str, float]:
        """将文本嵌入为 TF-IDF 向量"""
        terms = self._tokenize(text)
        term_freq: dict[str, int] = {}
        for term in terms:
            term_freq[term] = term_freq.get(term, 0) + 1

        embedding = {}
        for term, tf in term_freq.items():
            idf = self._idf.get(term, 1.0)
            embedding[term] = math.log(1 + tf) * idf

        return embedding

    def cosine_similarity(
        self,
        vec_a: dict[str, float],
        vec_b: dict[str, float],
    ) -> float:
        """计算余弦相似度"""
        all_keys = set(vec_a) | set(vec_b)
        if not all_keys:
            return 0.0

        dot_product = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in all_keys)
        norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
        norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def _tokenize(self, text: str) -> list[str]:
        """分词"""
        text = text.lower()
        text = re.sub(r'[\s\-\_\.\:\,\/\\\(\)\[\]\{\}\"\']', ' ', text)
        terms = text.split()
        terms = [t for t in terms if len(t) > 2]
        return terms


# ============================================================================
# RL Experience Hub
# ============================================================================


class RLExperienceHub:
    """强化学习经验回传中心

    提供:
    - 任务经验记录与持久化
    - 历史最优方案检索
    - 高频失败模式预警
    - 跨任务自学支持
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        max_experiences: int = 5000,
        project_ctx: Any = None,
    ) -> None:
        """初始化经验中心

        参数:
            db_path: SQLite 数据库路径 (显式指定时优先使用)
            max_experiences: 最大经验条数
            project_ctx: 项目上下文 (用于自动推导路径)
        """
        if db_path is not None:
            self.db_path = Path(db_path)
        elif project_ctx is not None:
            self.db_path = project_ctx.clawd_dir / 'rl_experience.db'
        else:
            # 向后兼容：使用相对路径
            self.db_path = Path('.clawd') / 'rl_experience.db'

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_experiences = max_experiences
        self._embedder = ExperienceEmbedder()
        self._ensure_db()

    def _ensure_db(self) -> None:
        """确保数据库表存在"""
        with self._connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS experiences (
                    id TEXT PRIMARY KEY,
                    task_description TEXT NOT NULL,
                    solution TEXT,
                    success INTEGER NOT NULL,
                    error_pattern TEXT,
                    tags TEXT,
                    execution_time_seconds REAL DEFAULT 0,
                    created_at REAL NOT NULL,
                    success_count INTEGER DEFAULT 1,
                    failure_count INTEGER DEFAULT 0,
                    embedding TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS failure_patterns (
                    pattern TEXT PRIMARY KEY,
                    frequency INTEGER DEFAULT 1,
                    last_seen REAL NOT NULL,
                    related_tags TEXT,
                    example_error TEXT
                )
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_created_at ON experiences(created_at)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_success ON experiences(success)
            ''')
            conn.commit()

    @contextmanager
    def _connect(self):
        """获取数据库连接"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute('PRAGMA journal_mode=WAL')
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def record_task_experience(
        self,
        task_description: str,
        solution: str,
        success: bool,
        error_pattern: str | None = None,
        tags: list[str] | None = None,
        execution_time_seconds: float = 0.0,
    ) -> str:
        """记录任务经验

        参数:
            task_description: 任务描述
            solution: 解决方案描述
            success: 是否成功
            error_pattern: 失败时的错误模式
            tags: 标签列表
            execution_time_seconds: 执行耗时

        返回:
            经验 ID
        """
        exp = TaskExperience(
            task_description=task_description,
            solution=solution,
            success=success,
            error_pattern=error_pattern or "",
            tags=tags or [],
            execution_time_seconds=execution_time_seconds,
        )
        exp.generate_id()

        with self._connect() as conn:
            # 检查是否已存在
            existing = conn.execute(
                'SELECT * FROM experiences WHERE id = ?', (exp.id,)
            ).fetchone()

            if existing:
                # 更新现有记录
                if success:
                    conn.execute(
                        'UPDATE experiences SET success_count = success_count + 1, solution = ? WHERE id = ?',
                        (exp.solution, exp.id),
                    )
                else:
                    conn.execute(
                        'UPDATE experiences SET failure_count = failure_count + 1, error_pattern = ? WHERE id = ?',
                        (exp.error_pattern, exp.id),
                    )
            else:
                # 插入新记录
                embedding = self._embedder.embed(f"{task_description} {solution}")
                success_count = 1 if success else 0
                failure_count = 0 if success else 1
                conn.execute(
                    '''INSERT INTO experiences
                       (id, task_description, solution, success, error_pattern, tags,
                        execution_time_seconds, created_at, success_count, failure_count, embedding)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        exp.id,
                        exp.task_description,
                        exp.solution,
                        1 if success else 0,
                        exp.error_pattern,
                        json.dumps(exp.tags, ensure_ascii=False),
                        exp.execution_time_seconds,
                        exp.created_at,
                        success_count,
                        failure_count,
                        json.dumps(embedding, ensure_ascii=False),
                    ),
                )

                # 检查是否需要清理旧经验
                count = conn.execute('SELECT COUNT(*) FROM experiences').fetchone()[0]
                if count > self.max_experiences:
                    self._prune_oldest(conn)

            conn.commit()

        # 如果是失败的任务，记录失败模式
        if not success and error_pattern:
            self._record_failure_pattern(error_pattern, tags or [])

        logger.info(f"记录任务经验: {exp.id} (success={success})")
        return exp.id

    def find_best_practices(
        self,
        query: str,
        top_k: int = 3,
        min_success_rate: float = 0.6,
    ) -> list[TaskExperience]:
        """查找历史最优解决方案

        参数:
            query: 查询文本 (如 "用户认证")
            top_k: 返回前 K 个结果
            min_success_rate: 最低成功率阈值

        返回:
            按综合评分排序的经验列表
        """
        query_embedding = self._embedder.embed(query)

        with self._connect() as conn:
            rows = conn.execute('SELECT * FROM experiences').fetchall()

        scored: list[tuple[float, TaskExperience]] = []

        for row in rows:
            exp = self._row_to_experience(row)

            # 检查成功率
            if exp.success_rate < min_success_rate:
                continue

            # 计算相似度
            if exp.embedding:
                similarity = self._embedder.cosine_similarity(query_embedding, exp.embedding)
            else:
                # 降级: 关键词匹配
                similarity = self._keyword_similarity(query, exp.task_description)

            # 综合评分: 相似度 * 成功率 * 尝试次数权重
            attempt_weight = min(1.0, exp.total_attempts / 3.0)
            score = similarity * exp.success_rate * (0.6 + 0.4 * attempt_weight)

            if score > 0:
                scored.append((score, exp))

        # 排序并返回
        scored.sort(key=lambda x: x[0], reverse=True)
        return [exp for _, exp in scored[:top_k]]

    def get_failure_warnings(self, query: str) -> list[FailurePattern]:
        """获取高频失败模式警告

        参数:
            query: 查询文本

        返回:
            相关的失败模式列表 (按频率排序)
        """
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM failure_patterns ORDER BY frequency DESC LIMIT 20'
            ).fetchall()

        patterns = []
        for row in rows:
            pattern = FailurePattern(
                pattern=row['pattern'],
                frequency=row['frequency'],
                last_seen=row['last_seen'],
                related_tags=json.loads(row['related_tags']) if row['related_tags'] else [],
                example_error=row['example_error'],
            )
            # 检查相关性
            if self._is_pattern_relevant(query, pattern):
                patterns.append(pattern)

        # 按频率排序
        patterns.sort(key=lambda p: p.frequency, reverse=True)
        return patterns[:5]

    def get_stats(self) -> dict[str, Any]:
        """获取经验统计信息"""
        with self._connect() as conn:
            total = conn.execute('SELECT COUNT(*) FROM experiences').fetchone()[0]
            success_total = conn.execute(
                'SELECT SUM(success_count) FROM experiences'
            ).fetchone()[0] or 0
            failure_total = conn.execute(
                'SELECT SUM(failure_count) FROM experiences'
            ).fetchone()[0] or 0
            avg_time = conn.execute(
                'SELECT AVG(execution_time_seconds) FROM experiences WHERE execution_time_seconds > 0'
            ).fetchone()[0] or 0

        overall_rate = 0.0
        if success_total + failure_total > 0:
            overall_rate = success_total / (success_total + failure_total)

        return {
            'total_experiences': total,
            'total_success_attempts': success_total,
            'total_failures': failure_total,
            'overall_success_rate': overall_rate,
            'average_execution_time': avg_time,
        }

    def _record_failure_pattern(
        self,
        error_pattern: str,
        tags: list[str],
    ) -> None:
        """记录失败模式"""
        # 提取关键错误模式 (简化)
        key_pattern = self._extract_key_pattern(error_pattern)

        with self._connect() as conn:
            existing = conn.execute(
                'SELECT * FROM failure_patterns WHERE pattern = ?', (key_pattern,)
            ).fetchone()

            if existing:
                conn.execute(
                    'UPDATE failure_patterns SET frequency = frequency + 1, last_seen = ?, related_tags = ?, example_error = ? WHERE pattern = ?',
                    (
                        time.time(),
                        json.dumps(tags, ensure_ascii=False),
                        error_pattern[:500],
                        key_pattern,
                    ),
                )
            else:
                conn.execute(
                    '''INSERT INTO failure_patterns (pattern, frequency, last_seen, related_tags, example_error)
                       VALUES (?, 1, ?, ?, ?)''',
                    (
                        key_pattern,
                        time.time(),
                        json.dumps(tags, ensure_ascii=False),
                        error_pattern[:500],
                    ),
                )
            conn.commit()

    def _extract_key_pattern(self, error: str) -> str:
        """提取关键错误模式"""
        # 简化: 取错误类型和关键信息
        match = re.search(r'(\w+Error|Exception)[:\s]+(.{0,100})', error)
        if match:
            return f"{match.group(1)}: {match.group(2).strip()[:50]}"
        return error[:100]

    def _is_pattern_relevant(self, query: str, pattern: FailurePattern) -> bool:
        """检查失败模式是否与查询相关"""
        query_lower = query.lower()
        pattern_lower = pattern.pattern.lower()

        # 关键词重叠
        query_words = set(query_lower.split())
        pattern_words = set(pattern_lower.split())
        overlap = query_words & pattern_words

        return len(overlap) > 0 or any(tag in query_lower for tag in pattern.related_tags)

    def _keyword_similarity(self, query: str, text: str) -> float:
        """关键词相似度 (降级方案)"""
        q_words = set(query.lower().split())
        t_words = set(text.lower().split())

        if not q_words or not t_words:
            return 0.0

        intersection = q_words & t_words
        union = q_words | t_words

        return len(intersection) / len(union) if union else 0.0

    def _row_to_experience(self, row: sqlite3.Row) -> TaskExperience:
        """将数据库行转换为 TaskExperience"""
        return TaskExperience(
            id=row['id'],
            task_description=row['task_description'],
            solution=row['solution'],
            success=bool(row['success']),
            error_pattern=row['error_pattern'] or '',
            tags=json.loads(row['tags']) if row['tags'] else [],
            execution_time_seconds=row['execution_time_seconds'] or 0.0,
            created_at=row['created_at'],
            success_count=row['success_count'],
            failure_count=row['failure_count'],
            embedding=json.loads(row['embedding']) if row['embedding'] else {},
        )

    def _prune_oldest(self, conn: sqlite3.Connection) -> None:
        """清理最旧的经验"""
        oldest = conn.execute(
            'SELECT id FROM experiences ORDER BY created_at ASC LIMIT ?',
            (self.max_experiences // 10,),
        ).fetchall()

        if oldest:
            ids = [r['id'] for r in oldest]
            conn.execute(
                'DELETE FROM experiences WHERE id IN ({})'.format(','.join('?' * len(ids))),
                ids,
            )
            logger.info(f"清理了 {len(ids)} 条旧经验")
