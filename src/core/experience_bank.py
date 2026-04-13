"""Unified Experience Bank — 统一经验库

合并自:
    - src/workflow/experience_bank.py (基础经验库, Jaccard 相似度)
    - src/self_healing/experience_bank.py (向量化经验库, TF-IDF + 余弦相似度)

设计原则:
    - 单一真相源 (Single Source of Truth)
    - 向后兼容 (保留两个模块的公共 API)
    - 向量功能可选 (不依赖外部向量库)
    - 轻量级 (纯 CPU, 无 ML 依赖)

层级:
    1. Exact Hash Match (MD5 前缀匹配) — 最快
    2. Jaccard Similarity (关键词重叠) — 快速
    3. TF-IDF Cosine Similarity (语义相似度) — 精准

Usage:
        bank = ExperienceBank(storage_path=Path("~/.clawd/experience.json"))

        # 记录经验
        bank.record_experience(
            error_pattern="ModuleNotFoundError: No module named 'foo'",
            error_category="ImportError",
            fix_strategy="修复导入路径",
            fix_code="from .module import fn",
            success=True,
        )

        # 检索相似经验 (自动选择最佳匹配算法)
        similar = bank.find_similar(
            error_pattern="ModuleNotFoundError...",
            error_category="ImportError",
            top_k=5,
        )
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..memory.enterprise_ltm import EnterpriseLTM, ImplementationPattern, PatternType

logger = logging.getLogger(__name__)


# ─── 数据模型 ─────────────────────────────────────────────────────────


@dataclass
class ExperienceRecord:
    """统一经验记录 (合并 ExperienceRecord + ExperienceEntry)"""

    # 核心字段
    id: str = ""                            # 唯一 ID (向量模式生成)
    error_pattern: str = ""                 # 错误模式描述
    error_traceback: str = ""               # 完整错误堆栈 (向量模式)
    error_category: str = ""                # 错误类型
    fix_strategy: str = ""                  # 修复策略
    fix_code: str = ""                      # 修复代码
    fix_details: str = ""                   # 修复详情
    task_description: str = ""              # 任务描述

    # 统计字段
    times_used: int = 1                     # 使用次数
    application_count: int = 0              # 应用次数 (向量模式别名)
    success_count: int = 0                  # 成功次数
    fail_count: int = 0                     # 失败次数
    failure_count: int = 0                  # 失败次数 (向量模式别名)
    success_flag: bool = True               # 最新是否成功

    # 向量字段
    error_embedding: dict[str, float] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float:
        """成功率"""
        total = self.success_count + self.fail_count
        if total == 0:
            total = self.success_count + self.failure_count
        if total == 0:
            return 0.5
        return self.success_count / total

    def update(self, success: bool) -> None:
        """更新经验记录"""
        self.times_used += 1
        self.application_count = self.times_used
        if success:
            self.success_count += 1
            self.success_flag = True
        else:
            self.fail_count += 1
            self.failure_count += 1
            self.success_flag = False
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperienceRecord:
        valid_keys = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


# ─── 嵌入器 (TF-IDF 近似) ─────────────────────────────────────────


class ExperienceEmbedder:
    """轻量 TF-IDF 嵌入器

    将错误堆栈转换为向量，用于语义相似度计算。
    不依赖外部向量库，适合 CPU 环境。
    """

    ERROR_KEYWORDS = [
        "syntaxerror", "nameerror", "typeerror", "valueerror", "keyerror",
        "indexerror", "attributeerror", "importerror", "modulenotfounderror",
        "filenotfounderror", "permissionerror", "timeout", "connectionerror",
        "sslerror", "runtimeerror", "notimplementederror", "recursionerror",
        "memoryerror", "oserror", "ioerror", "unicodeerror",
        "traceback", "exception", "error", "failed", "crash",
        "undefined", "null", "none", "missing", "invalid",
    ]

    def __init__(self) -> None:
        self._idf: dict[str, float] = {}
        self._documents: list[str] = []
        self._built = False

    def fit(self, documents: list[str]) -> None:
        """构建 IDF 词汇表"""
        self._documents = documents
        doc_freq: dict[str, int] = {}

        for doc in documents:
            terms = self._tokenize(doc)
            for term in set(terms):
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

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """分词"""
        text = text.lower()
        text = re.sub(r'[\s\-\_\.\:\,\/\\\(\)\[\]\{\}]', ' ', text)
        terms = text.split()
        return [t for t in terms if len(t) > 2 and not t.isdigit()]


# ─── 统一经验库 ─────────────────────────────────────────────────────


class ExperienceBank:
    """统一经验库 — 合并基础 + 向量功能

    匹配策略 (从快到慢):
        1. Exact Hash Match (MD5 前缀) — O(1)
        2. Jaccard Similarity (关键词重叠) — O(n)
        3. TF-IDF Cosine Similarity (语义) — O(n)，最精准
    """

    def __init__(
        self,
        storage_path: Path | None = None,
        max_entries: int = 1000,
        enable_ltm: bool = True,
    ) -> None:
        if storage_path is None:
            # 默认路径优先级: 环境变量 > 项目本地 .clawd > 用户家目录
            raw_env_path = os.environ.get('CLAWGOD_EXPERIENCE_PATH', '')
            if raw_env_path.startswith('~'):
                env_path = raw_env_path.replace('~', str(Path.home()), 1)
            else:
                env_path = raw_env_path

            if env_path:
                self._storage_path = Path(env_path)
            elif Path('.clawd').exists():
                self._storage_path = Path('.clawd') / 'experience.json'
            else:
                self._storage_path = Path.home() / '.clawd' / 'experience.json'
        else:
            self._storage_path = storage_path

        self.max_entries = max_entries
        self._experiences: dict[str, ExperienceRecord] = {}
        self._embedder = ExperienceEmbedder()
        self._vector_mode = False  # 是否启用向量检索
        self._ltm = EnterpriseLTM() if enable_ltm else None
        self._background_tasks: set[asyncio.Task] = set()

    # ─── 公共 API (向后兼容 workflow 版) ──────────────────────

    def record_experience(
        self,
        error_pattern: str = "",
        error_category: str = "",
        fix_strategy: str = "",
        success: bool = True,
        task_description: str = "",
        fix_details: str = "",
        fix_code: str = "",
        error_traceback: str = "",
        tags: list[str] | None = None,
    ) -> ExperienceRecord:
        """记录修复经验

        兼容两种调用风格:
            - workflow 风格: error_pattern + fix_strategy
            - self_healing 风格: error_traceback + fix_code
        """
        # 生成 ID
        content_key = f"{error_traceback or error_pattern}:{fix_strategy}"
        content_hash = hashlib.md5(content_key[:150].encode()).hexdigest()[:8]
        exp_id = f"exp_{content_hash}"

        # 检查是否已存在
        existing = self._experiences.get(exp_id)
        if existing:
            existing.update(success)
            if fix_details:
                existing.fix_details = fix_details
            if fix_code:
                existing.fix_code = fix_code
            if tags:
                existing.tags = list(set(existing.tags + tags))
            self._save()
            return existing

        # 创建新经验
        entry = ExperienceRecord(
            id=exp_id,
            error_pattern=error_pattern,
            error_traceback=error_traceback[:2000],
            error_category=error_category,
            fix_strategy=fix_strategy,
            fix_code=fix_code,
            fix_details=fix_details,
            task_description=task_description,
            success_flag=success,
            success_count=1 if success else 0,
            fail_count=0 if success else 1,
            failure_count=0 if success else 1,
            tags=tags or [],
        )

        # 向量嵌入 (如果有 traceback)
        if error_traceback:
            entry.error_embedding = self._embedder.embed(error_traceback)
            self._vector_mode = True

        if len(self._experiences) >= self.max_entries:
            self._prune_oldest()

        self._experiences[exp_id] = entry
        self._save()

        # 如果启用 LTM 且修复成功，则持久化到企业级 LTM
        if self._ltm and success:
            import asyncio

            from ..brain.world_model import RepositoryWorldModel

            # 提取拓扑关联 (尝试获取全局 WorldModel 实例)
            # 这是一个轻量级注入
            related_files = []
            try:
                # 假设在工作目录中初始化
                wm = RepositoryWorldModel(root_dir=self._storage_path.parent.parent.parent if self._storage_path else Path.cwd())
                # 预测相关文件以增强 LTM 的上下文
                if error_pattern:
                    related_files = wm.predict_relevant_files(error_pattern)
            except Exception:
                pass

            pattern = ImplementationPattern(
                pattern_id=exp_id,
                task_type=error_category or "general_fix",
                description=error_pattern or task_description,
                solution_code=fix_code or fix_strategy,
                success_metrics={
                    "success_rate": 1.0,
                    "source": "experience_bank",
                    "topological_context": related_files[:5]
                },
                pattern_type=PatternType.SUCCESS
            )
            # 异步执行，不阻塞当前请求
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    task = loop.create_task(self._ltm.store_pattern(pattern))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                else:
                    asyncio.run(self._ltm.store_pattern(pattern))
            except Exception as e:
                logger.debug(f"LTM 持久化失败: {e}")

        return entry

    async def find_similar_ltm(
        self,
        query: str,
        limit: int = 3
    ) -> list[ImplementationPattern]:
        """从 Enterprise LTM 检索跨项目模式 (向量增强预留)"""
        if not self._ltm:
            return []
        return await self._ltm.find_similar_patterns(query, limit=limit)

    def find_similar_fix(
        self,
        error_pattern: str = "",
        error_category: str | None = None,
        min_success_rate: float = 0.5,
        top_k: int = 5,
        error_traceback: str = "",
    ) -> ExperienceRecord | list[ExperienceRecord] | Any:
        """查找相似的修复方案

        自动选择最佳匹配策略:
            - 有 traceback → 向量语义检索
            - 仅有 pattern → Jaccard 关键词匹配

        返回:
            单个记录 (workflow 兼容) 或列表 (向量模式)
        """
        # 策略 1: 向量语义检索 (最精准)
        if error_traceback and self._vector_mode:
            return self._find_by_vector(error_traceback, top_k, min_success_rate)

        # 策略 2: Jaccard 关键词匹配 (快速)
        candidates = []
        for exp in self._experiences.values():
            if exp.success_rate < min_success_rate:
                continue
            if error_category and exp.error_category != error_category:
                continue

            similarity = self._calculate_similarity(error_pattern, exp.error_pattern)
            if similarity > 0.3:
                candidates.append((similarity, exp))

        if not candidates:
            return None if not error_traceback else []

        candidates.sort(key=lambda x: x[0], reverse=True)

        # 返回单个 (workflow 兼容) 或列表
        if not error_traceback:
            return candidates[0][1]
        return [exp for _, exp in candidates[:top_k]]

    async def find_similar_combined(
        self,
        error_traceback: str,
        top_k: int = 5,
        min_success_rate: float = 0.5,
    ) -> list[Any]:
        """结合本地经验库和企业级 LTM 进行深度检索 (v0.66)"""
        # 1. 获取本地相似经验
        local_results = self.find_similar(error_traceback, top_k=top_k, min_success_rate=min_success_rate)

        # 2. 获取企业级 LTM 模式
        ltm_results = []
        if self._ltm:
            try:
                ltm_results = await self._ltm.find_similar_patterns(error_traceback, limit=top_k)
            except Exception as e:
                logger.debug(f"LTM 检索失败: {e}")

        # 3. 合并并去重 (简化逻辑: LTM 结果转换为本地格式或保留原始)
        # 实际自愈引擎目前能处理多种格式
        return list(local_results) + list(ltm_results)

    def find_similar(
        self,
        error_traceback: str,
        top_k: int = 5,
        min_success_rate: float = 0.0,
    ) -> list[ExperienceRecord]:
        """向量模式下的相似检索 (self_healing 兼容 API)"""
        result = self.find_similar_fix(
            error_traceback=error_traceback,
            top_k=top_k,
            min_success_rate=min_success_rate,
        )
        return result if isinstance(result, list) else ([result] if result else [])

    def update_success(self, exp_id: str, success: bool) -> bool:
        """更新经验成功标记"""
        exp = self._experiences.get(exp_id)
        if not exp:
            return False
        exp.update(success)
        self._save()
        return True

    def get_stats(self) -> dict[str, Any]:
        """获取经验统计"""
        if not self._experiences:
            return {"total": 0, "total_experiences": 0, "overall_success_rate": 0.0}

        total_success = sum(e.success_count for e in self._experiences.values())
        total_failure = sum(e.fail_count for e in self._experiences.values())

        by_category: dict[str, int] = defaultdict(int)
        for e in self._experiences.values():
            cat = e.error_category or "unknown"
            by_category[cat] += 1

        return {
            "total": len(self._experiences),
            "total_experiences": len(self._experiences),
            "total_success": total_success,
            "total_failure": total_failure,
            "total_applications": sum(e.application_count for e in self._experiences.values()),
            "overall_success_rate": total_success / max(total_success + total_failure, 1),
            "by_category": dict(by_category),
            "vector_mode": self._vector_mode,
        }

    def clear(self) -> None:
        """清空经验库"""
        self._experiences.clear()
        self._embedder = ExperienceEmbedder()
        self._vector_mode = False
        self._save()

    # ─── 内部方法 ──────────────────────────────────────────────

    def _find_by_vector(
        self,
        error_traceback: str,
        top_k: int,
        min_success_rate: float,
    ) -> list[ExperienceRecord]:
        """向量语义检索"""
        query_embedding = self._embedder.embed(error_traceback)
        scored: list[tuple[float, ExperienceRecord]] = []

        for exp in self._experiences.values():
            if not exp.error_embedding:
                continue

            similarity = self._embedder.cosine_similarity(
                query_embedding, exp.error_embedding,
            )
            success_rate = exp.success_rate
            application_weight = min(1.0, exp.application_count / 5.0)
            combined_score = similarity * success_rate * (0.7 + 0.3 * application_weight)

            if combined_score > 0 and success_rate >= min_success_rate:
                scored.append((combined_score, exp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [exp for _, exp in scored[:top_k]]

    def _find_similar(
        self,
        error_pattern: str,
        error_category: str,
        threshold: float = 0.7,
    ) -> ExperienceRecord | None:
        """查找相似经验记录 (内部方法，workflow 兼容)"""
        for exp in self._experiences.values():
            if exp.error_category != error_category:
                continue
            similarity = self._calculate_similarity(error_pattern, exp.error_pattern)
            if similarity >= threshold:
                return exp
        return None

    @staticmethod
    def _calculate_similarity(pattern1: str, pattern2: str) -> float:
        """Jaccard 相似度 (关键词匹配)"""
        if not pattern1 or not pattern2:
            return 0.0
        words1 = set(_tokenize(pattern1))
        words2 = set(_tokenize(pattern2))
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union) if union else 0.0

    def _prune_oldest(self) -> None:
        """删除最旧的经验"""
        if not self._experiences:
            return
        oldest_id = min(
            self._experiences,
            key=lambda x: self._experiences[x].created_at,
        )
        del self._experiences[oldest_id]

    def _save(self) -> None:
        """持久化经验库"""
        if not self._storage_path:
            return
        try:
            data = {
                "version": "2.0",
                "unified": True,
                "experiences": {
                    eid: exp.to_dict()
                    for eid, exp in self._experiences.items()
                },
            }
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning(f"经验库保存失败: {e}")

    def load(self) -> int:
        """Public load method (alias for _load)."""
        return self._load()

    def _load(self) -> int:
        """加载经验库

        自动兼容旧格式 (workflow list) 和新格式 (unified dict)。
        """
        if not self._storage_path or not self._storage_path.exists():
            return 0

        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))

            # 新格式 (Unified Experience Bank)
            if isinstance(raw, dict) and "experiences" in raw:
                self._experiences = {
                    eid: ExperienceRecord.from_dict(edata)
                    for eid, edata in raw["experiences"].items()
                }
            # 旧格式 (workflow ExperienceBank list)
            elif isinstance(raw, list):
                for d in raw:
                    exp = ExperienceRecord.from_dict(d)
                    if not exp.id:
                        content_hash = hashlib.md5(
                            f"{exp.error_pattern}:{exp.fix_strategy}".encode()
                        ).hexdigest()[:8]
                        exp.id = f"exp_{content_hash}"
                    self._experiences[exp.id] = exp
            # 旧格式 (self_healing VectorExperienceBank)
            elif isinstance(raw, dict) and "version" in raw:
                for eid, edata in raw.get("experiences", {}).items():
                    self._experiences[eid] = ExperienceRecord.from_dict(edata)

            # 重建嵌入器
            self._rebuild_embedder()

            count = len(self._experiences)
            if count:
                logger.info(f"经验库已加载: {count} 条记录 (vector_mode={self._vector_mode})")
            return count

        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning(f"经验库加载失败: {e}")
            return 0

    def _rebuild_embedder(self) -> None:
        """重建嵌入器"""
        documents = [
            exp.error_traceback
            for exp in self._experiences.values()
            if exp.error_traceback
        ]
        if documents:
            self._embedder.fit(documents)
            self._vector_mode = True


# ─── 工具函数 ─────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """简单分词 (中英文混合)"""
    return re.findall(r'[a-zA-Z0-9_]+|[\u4e00-\u9fff]+', text.lower())
