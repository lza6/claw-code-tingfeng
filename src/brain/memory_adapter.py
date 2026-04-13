"""Memory Adapter — SQLite 原子级读写适配器

存储在 `项目目录/.clawd/brain/patterns.db` (SQLite)，
负责 Brain 模块所有数据的原子级读写。

表结构:
- brain_rules: 自动生成的强制规则
- failure_sequences: 失败序列模式
- success_vectors: 成功特征向量
- optimization_advice: 优化建议
- entropy_reports: 语义熵报告
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..core.project_context import ProjectContext
from .models import (
    BrainRule,
    EntropyReport,
    FailureSequence,
    OptimizationAdvice,
    SuccessVector,
)

# 默认路径（向后兼容）
DEFAULT_DB_DIR = Path('.clawd') / 'brain'


class MemoryAdapter:
    """SQLite 持久化适配器"""

    def __init__(self, db_dir: Path | None = None, project_ctx: ProjectContext | None = None) -> None:
        """初始化 SQLite 持久化适配器

        Args:
            db_dir: 数据库目录（显式指定时优先使用）
            project_ctx: 项目上下文（用于自动推导路径）
        """
        if db_dir is not None:
            self._db_dir = db_dir
        elif project_ctx is not None:
            self._db_dir = project_ctx.brain_dir
        else:
            self._db_dir = DEFAULT_DB_DIR
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._db_dir / "patterns.db"
        self._init_db()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接"""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """初始化数据库表"""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS brain_rules (
                    id TEXT PRIMARY KEY,
                    rule_text TEXT NOT NULL,
                    trigger_error TEXT,
                    trigger_count INTEGER DEFAULT 0,
                    platform TEXT,
                    tool_name TEXT,
                    severity TEXT DEFAULT 'warning',
                    created_at REAL,
                    enforced INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS failure_sequences (
                    id TEXT PRIMARY KEY,
                    tool_name TEXT,
                    error_type TEXT,
                    error_messages TEXT,
                    occurrences INTEGER DEFAULT 0,
                    first_seen REAL,
                    last_seen REAL,
                    context TEXT
                );

                CREATE TABLE IF NOT EXISTS success_vectors (
                    id TEXT PRIMARY KEY,
                    goal TEXT,
                    steps TEXT,
                    tools_used TEXT,
                    tool_feedback TEXT,
                    tags TEXT,
                    embedding TEXT,
                    success_score REAL,
                    created_at REAL,
                    access_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS optimization_advice (
                    id TEXT PRIMARY KEY,
                    advice_type TEXT,
                    description TEXT,
                    prompt_patch TEXT,
                    config_changes TEXT,
                    affected_tools TEXT,
                    confidence REAL,
                    created_at REAL
                );

                CREATE TABLE IF NOT EXISTS entropy_reports (
                    id TEXT PRIMARY KEY,
                    file_path TEXT,
                    entropy_score REAL,
                    risk_level TEXT,
                    contributing_factors TEXT,
                    hotspots TEXT,
                    recommendations TEXT,
                    analyzed_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_rules_severity ON brain_rules(severity);
                CREATE INDEX IF NOT EXISTS idx_failures_tool ON failure_sequences(tool_name);
                CREATE INDEX IF NOT EXISTS idx_failures_type ON failure_sequences(error_type);
                CREATE INDEX IF NOT EXISTS idx_vectors_goal ON success_vectors(goal);
                CREATE INDEX IF NOT EXISTS idx_vectors_score ON success_vectors(success_score);
            """)

    # ========================================================================
    # Brain Rules CRUD
    # ========================================================================

    def save_rule(self, rule: BrainRule) -> str:
        """保存规则"""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO brain_rules
                   (id, rule_text, trigger_error, trigger_count, platform,
                    tool_name, severity, created_at, enforced)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rule.id, rule.rule_text, rule.trigger_error,
                    rule.trigger_count, rule.platform, rule.tool_name,
                    rule.severity, rule.created_at, int(rule.enforced),
                ),
            )
        return rule.id

    def get_rules(self, platform: str | None = None,
                  tool_name: str | None = None) -> list[BrainRule]:
        """获取规则 (可按平台/工具过滤)"""
        with self._connect() as conn:
            query = "SELECT * FROM brain_rules WHERE enforced = 1"
            params: list[Any] = []
            if platform:
                query += " AND (platform = ? OR platform = '')"
                params.append(platform)
            if tool_name:
                query += " AND (tool_name = ? OR tool_name = '')"
                params.append(tool_name)
            query += " ORDER BY severity DESC, trigger_count DESC"
            rows = conn.execute(query, params).fetchall()
            return [BrainRule(
                id=r["id"], rule_text=r["rule_text"],
                trigger_error=r["trigger_error"],
                trigger_count=r["trigger_count"],
                platform=r["platform"], tool_name=r["tool_name"],
                severity=r["severity"], created_at=r["created_at"],
                enforced=bool(r["enforced"]),
            ) for r in rows]

    # ========================================================================
    # Failure Sequences CRUD
    # ========================================================================

    def save_failure_sequence(self, seq: FailureSequence) -> str:
        """保存失败序列"""
        seq_id = f"{seq.tool_name}:{seq.error_type}"
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO failure_sequences
                   (id, tool_name, error_type, error_messages,
                    occurrences, first_seen, last_seen, context)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    seq_id, seq.tool_name, seq.error_type,
                    json.dumps(seq.error_messages, ensure_ascii=False),
                    seq.occurrences, seq.first_seen, seq.last_seen,
                    json.dumps(seq.context, ensure_ascii=False),
                ),
            )
        return seq_id

    def get_failure_sequences(
        self, min_occurrences: int = 1
    ) -> list[FailureSequence]:
        """获取失败序列"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM failure_sequences WHERE occurrences >= ?",
                (min_occurrences,),
            ).fetchall()
            return [
                FailureSequence(
                    tool_name=r["tool_name"],
                    error_type=r["error_type"],
                    error_messages=json.loads(r["error_messages"]),
                    occurrences=r["occurrences"],
                    first_seen=r["first_seen"],
                    last_seen=r["last_seen"],
                    context=json.loads(r["context"]) if r["context"] else {},
                )
                for r in rows
            ]

    # ========================================================================
    # Success Vectors CRUD
    # ========================================================================

    def save_success_vector(self, vec: SuccessVector) -> str:
        """保存成功向量"""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO success_vectors
                   (id, goal, steps, tools_used, tool_feedback, tags,
                    embedding, success_score, created_at, access_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    vec.id, vec.goal,
                    json.dumps(vec.steps, ensure_ascii=False),
                    json.dumps(vec.tools_used, ensure_ascii=False),
                    json.dumps(vec.tool_feedback, ensure_ascii=False),
                    json.dumps(vec.tags, ensure_ascii=False),
                    json.dumps(vec.embedding),
                    vec.success_score, vec.created_at, vec.access_count,
                ),
            )
        return vec.id

    def get_success_vectors(
        self, top_k: int = 5
    ) -> list[SuccessVector]:
        """获取成功向量 (按访问次数和分数排序)"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM success_vectors
                   ORDER BY success_score DESC, access_count DESC
                   LIMIT ?""",
                (top_k,),
            ).fetchall()
            return [SuccessVector.from_dict(dict(r)) for r in rows]

    # ========================================================================
    # Optimization Advice CRUD
    # ========================================================================

    def save_advice(self, advice: OptimizationAdvice) -> str:
        """保存优化建议"""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO optimization_advice
                   (id, advice_type, description, prompt_patch,
                    config_changes, affected_tools, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    advice.id, advice.advice_type, advice.description,
                    advice.prompt_patch,
                    json.dumps(advice.config_changes),
                    json.dumps(advice.affected_tools),
                    advice.confidence, advice.created_at,
                ),
            )
        return advice.id

    def get_advice(self, limit: int = 10) -> list[OptimizationAdvice]:
        """获取优化建议"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM optimization_advice
                   ORDER BY confidence DESC, created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [OptimizationAdvice.from_dict(dict(r)) for r in rows]

    # ========================================================================
    # Entropy Reports CRUD
    # ========================================================================

    def save_entropy_report(self, report: EntropyReport) -> str:
        """保存熵报告"""
        report_id = report.file_path or str(hash(report.analyzed_at))
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO entropy_reports
                   (id, file_path, entropy_score, risk_level,
                    contributing_factors, hotspots, recommendations,
                    analyzed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report_id, report.file_path, report.entropy_score,
                    report.risk_level,
                    json.dumps(report.contributing_factors),
                    json.dumps(report.hotspots),
                    json.dumps(report.recommendations),
                    report.analyzed_at,
                ),
            )
        return report_id

    def get_high_entropy_files(
        self, threshold: float = 0.5
    ) -> list[EntropyReport]:
        """获取高熵文件报告"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM entropy_reports
                   WHERE entropy_score >= ?
                   ORDER BY entropy_score DESC""",
                (threshold,),
            ).fetchall()
            return [
                EntropyReport(
                    file_path=r["file_path"],
                    entropy_score=r["entropy_score"],
                    risk_level=r["risk_level"],
                    contributing_factors=json.loads(r["contributing_factors"]),
                    hotspots=json.loads(r["hotspots"]),
                    recommendations=json.loads(r["recommendations"]),
                    analyzed_at=r["analyzed_at"],
                )
                for r in rows
            ]

    # ========================================================================
    # Cleanup
    # ========================================================================

    def cleanup(self, max_rules: int = 100, max_vectors: int = 200) -> None:
        """清理旧数据，防止数据库无限增长"""
        with self._connect() as conn:
            # 保留最新的 rules
            conn.execute(
                """DELETE FROM brain_rules
                   WHERE id NOT IN (
                       SELECT id FROM brain_rules
                       ORDER BY created_at DESC LIMIT ?
                   )""",
                (max_rules,),
            )
            # 保留最高分的 success vectors
            conn.execute(
                """DELETE FROM success_vectors
                   WHERE id NOT IN (
                       SELECT id FROM success_vectors
                       ORDER BY success_score DESC, access_count DESC
                       LIMIT ?
                   )""",
                (max_vectors,),
            )
