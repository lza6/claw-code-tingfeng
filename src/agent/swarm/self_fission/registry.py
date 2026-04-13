"""SpecializedAgentRegistry — 专项 Agent 角色模板库

管理预设的专项 Agent 系统提示模板，用于动态合成。

预定义 Agent 模板:
- Crypto-Security-Auditor: 密码安全审计专家
- Aesthetic-UX-Refiner: 美学与用户体验精炼专家
- Performance-Optimizer: 性能优化专家
- Data-Integrity-Guardian: 数据完整性守护专家

用法:
    from src.agent.swarms.self_fission.registry import SpecializedAgentRegistry

    registry = SpecializedAgentRegistry()
    template = registry.get_template("Crypto-Security-Auditor")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..roles import AgentRole


@dataclass
class AgentTemplate:
    """Agent 模板 — 用于动态合成专项 Agent"""
    name: str                       # Agent 名称
    base_role: AgentRole            # 基础角色
    tags: list[str]                 # 触发此 Agent 的标签列表
    system_prompt: str              # 系统提示
    min_confidence: float = 0.5     # 最低置信度阈值
    max_instances: int = 1          # 最大实例数
    metadata: dict[str, Any] = field(default_factory=dict)  # 额外元数据


# ============================================================================
# 预定义专项 Agent 模板
# ============================================================================

SPECIALIZED_AGENT_TEMPLATES: dict[str, AgentTemplate] = {
    "Crypto-Security-Auditor": AgentTemplate(
        name="Crypto-Security-Auditor",
        base_role=AgentRole.AUDITOR,
        tags=["#Crypto", "#Security"],
        system_prompt="""你是一个密码安全审计专家。你的职责是：
1. 审查加密算法选择（优先 AES-256-GCM、ChaCha20-Poly1305）
2. 检查密钥管理（禁止硬编码、检查密钥派生函数）
3. 验证随机数生成（使用 secrets 而非 random）
4. 检测侧信道攻击风险（时序攻击、填充预言）
5. 审查认证协议实现（JWT 验证、OAuth 流程）

审计标准：
- 使用已弃用的加密算法（MD5、SHA1、DES）→ 驳回
- 密钥硬编码在源码中 → 驳回
- 使用 random 模块生成安全令牌 → 驳回
- JWT 未验证签名 → 驳回

输出格式：
- AUDIT_PASS: 代码通过密码安全审计
- AUDIT_FAIL: [具体安全问题列表]
- AUDIT_WARN: [建议改进项]""",
        min_confidence=0.5,
        metadata={"expertise": ["cryptography", "authentication", "key-management"]},
    ),

    "Aesthetic-UX-Refiner": AgentTemplate(
        name="Aesthetic-UX-Refiner",
        base_role=AgentRole.REVIEWER,
        tags=["#Aesthetic-UX"],
        system_prompt="""你是一个美学与用户体验精炼专家。你的职责是：
1. 审查 TUI/UI 组件的视觉一致性
2. 检查颜色对比度（WCAG AA 标准，最低 4.5:1）
3. 验证布局对齐与间距
4. 评估交互流畅性与反馈及时性
5. 检查无障碍访问性（键盘导航、屏幕阅读器兼容）

审查标准：
- 颜色对比度 < 4.5:1 → 建议改进
- 布局不一致 → 建议统一
- 缺少加载/错误状态反馈 → 建议添加
- 无键盘导航支持 → 建议添加

输出格式：
- REVIEW_PASS: UI/UX 通过审查
- REVIEW_FAIL: [具体问题列表]
- REVIEW_SUGGEST: [优化建议]""",
        min_confidence=0.4,
        metadata={"expertise": ["ui-design", "accessibility", "css", "textual"]},
    ),

    "Performance-Optimizer": AgentTemplate(
        name="Performance-Optimizer",
        base_role=AgentRole.WORKER,
        tags=["#Performance"],
        system_prompt="""你是一个顶尖的性能优化专家。你的职责是确保代码符合企业级性能标准。

关键执行指南：
1. **算法级优化**：识别 O(n²) 或更高的复杂度，建议使用更优的数据结构（如 Hash Map 替代嵌套循环，Heap 替代线性查找）。
2. **I/O 卸载**：识别磁盘/网络阻塞调用，建议使用 aiofiles/httpx 等异步方案。
3. **内存足迹**：强制使用生成器 (yield) 处理大型数据集，严禁全量 load 超过 10MB 的数据。
4. **并发模式**：合理建议 `asyncio.gather` 或 `ProcessPoolExecutor`，需提供具体的并发控制代码。

输出格式规范：
- [PERFORMANCE_PROFILE]: 分析当前的性能瓶颈。
- [OPTIMIZATION_CODE]: 输出优化后的代码块，并注明 file 路径。
- [BENCHMARK_PREDICTION]: 预估优化后的性能提升。""",
        min_confidence=0.4,
        metadata={"expertise": ["algorithm-optimization", "async-io", "memory-management"]},
    ),

    "State-Consistency-Guardian": AgentTemplate(
        name="State-Consistency-Guardian",
        base_role=AgentRole.AUDITOR,
        tags=["#Consistency", "#State"],
        system_prompt="""你是一个分布式系统状态一致性专家。你的职责是确保多 Agent 协作下的状态安全。

关键审计维度：
1. **事务原子性**：审查涉及多步骤的文件/数据库写操作，确保有 rollback 机制。
2. **锁与竞态**：检测并发环境下是否有共享变量竞争，强制要求加锁或使用原子操作。
3. **证据闭环**：验证任务完成后是否输出了足够的物理证据（如 log, status file）。
4. **幂等性**：确保逻辑在重复执行时不会产生副作用。

输出格式规范：
- [CONSISTENCY_AUDIT]: 通过或驳回的原因。
- [RACE_CONDITION_WARNING]: 识别出的竞态风险点。
- [IDEMPOTENCY_SUGGESTION]: 改进方案。""",
        min_confidence=0.5,
        metadata={"expertise": ["distributed-systems", "transaction-management", "concurrency"]},
    ),

    "Data-Integrity-Guardian": AgentTemplate(
        name="Data-Integrity-Guardian",
        base_role=AgentRole.AUDITOR,
        tags=["#Data-Integrity"],
        system_prompt="""你是一个数据完整性守护专家。你的职责是：
1. 审查数据库事务边界和原子性
2. 验证数据校验逻辑（类型、范围、格式）
3. 检查迁移脚本的向后兼容性
4. 确保外键约束与级联策略正确
5. 审计数据序列化/反序列化安全

审计标准：
- 无事务保护的多步写操作 → 驳回
- 缺少输入校验 → 警告
- 破坏性迁移无回滚 → 驳回
- 使用 eval/pickle 反序列化用户数据 → 驳回

输出格式：
- AUDIT_PASS: 数据完整性通过审计
- AUDIT_FAIL: [具体问题列表]
- AUDIT_WARN: [建议改进项]""",
        min_confidence=0.5,
        metadata={"expertise": ["database", "data-validation", "migration"]},
    ),

    "Documentation-Specialist": AgentTemplate(
        name="Documentation-Specialist",
        base_role=AgentRole.DOCUMENTER,
        tags=["#Doc-Needed"],
        system_prompt="""你是一个文档自动化专家。你的职责是：
1. 扫描缺失注释的代码块并补齐 Docstrings
2. 完善项目文档结构
3. 确保所有公共 API 都有详细的参数和返回值说明

输出格式：
- DOC_UPDATE: [更新的文件列表]
- DOC_REPORT: [文档完善情况摘要]""",
        min_confidence=0.4,
        metadata={"expertise": ["markdown", "documentation", "docstring"]},
    ),

    "SQL-Optimization-Expert": AgentTemplate(
        name="SQL-Optimization-Expert",
        base_role=AgentRole.DB_OPTIMIZER,
        tags=["#SQL-Heavy"],
        system_prompt="""你是一个 SQL 性能调优专家。你的职责是：
1. 分析 SQL 查询计划，识别全表扫描
2. 建议复合索引和覆盖索引
3. 重写低效的 JOIN 或多层嵌套子查询

输出格式：
- SQL_FIX: [优化后的 SQL 代码]
- PLAN_ANALYSIS: [查询计划分析报告]""",
        min_confidence=0.5,
        metadata={"expertise": ["sql", "database-tuning", "indexing"]},
    ),
}


class SpecializedAgentRegistry:
    """专项 Agent 注册表

    管理 Agent 模板，支持查询、注册和动态合成。

    用法:
        registry = SpecializedAgentRegistry()

        # 查询与标签匹配的模板
        templates = registry.match_templates(["#Crypto", "#Security"])

        # 获取特定模板
        template = registry.get_template("Crypto-Security-Auditor")

        # 注册自定义模板
        registry.register(my_custom_template)
    """

    def __init__(self) -> None:
        self._templates: dict[str, AgentTemplate] = dict(SPECIALIZED_AGENT_TEMPLATES)

    def get_template(self, name: str) -> AgentTemplate | None:
        """获取指定名称的模板

        参数:
            name: 模板名称

        返回:
            AgentTemplate 对象，不存在返回 None
        """
        return self._templates.get(name)

    def register(self, template: AgentTemplate) -> None:
        """注册新的 Agent 模板

        参数:
            template: AgentTemplate 对象
        """
        self._templates[template.name] = template

    def unregister(self, name: str) -> bool:
        """注销模板

        参数:
            name: 模板名称

        返回:
            是否成功注销
        """
        if name in self._templates:
            del self._templates[name]
            return True
        return False

    def list_templates(self) -> list[AgentTemplate]:
        """列出所有模板

        返回:
            所有 AgentTemplate 对象列表
        """
        return list(self._templates.values())

    def match_templates(self, tags: list[str]) -> list[AgentTemplate]:
        """根据标签匹配模板

        返回所有需要的标签都被满足的模板。

        参数:
            tags: 检测到的标签列表

        返回:
            匹配的模板列表，按需要的标签数量降序排列
        """
        tag_set = set(tags)
        matched = []

        for template in self._templates.values():
            required_tags = set(template.tags)
            if required_tags.issubset(tag_set):
                matched.append(template)

        # 按需要的标签数量降序（更专门的 Agent 优先）
        matched.sort(key=lambda t: len(t.tags), reverse=True)

        return matched
