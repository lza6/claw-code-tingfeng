"""Coder Agent — 领域专家执行"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...llm import LLMConfig
from ..engine import AgentEngine
from ..factory import create_agent_engine
from .base_agent import BaseAgent
from .consensus import SemanticValidator, Vote, VoteType
from .message_bus import AgentMessage, MessageBus, MessageType
from .roles import AgentRole

logger = logging.getLogger(__name__)


@dataclass
class CodeExpertise:
    """代码专家能力"""
    domain: str                    # 领域 (e.g., "frontend", "backend", "database")
    languages: list[str]           # 擅长语言
    frameworks: list[str]          # 擅长框架
    confidence: float = 0.0        # 置信度 0.0 - 1.0


@dataclass
class CodeSubmission:
    """代码提交"""
    submission_id: str
    coder_id: str
    code: str
    file_path: str
    domain: str
    explanation: str = ""
    timestamp: float = field(default_factory=time.time)


class CoderAgent(BaseAgent):
    """Coder Agent — 领域专家执行

    职责:
    1. 根据架构规划编写代码
    2. 实现测试用例
    3. 提交代码供审计
    4. 根据反馈修改
    """

    def __init__(
        self,
        agent_id: str = "coder-1",
        message_bus: MessageBus | None = None,
        llm_config: LLMConfig | None = None,
        workdir: Path | None = None,
        domain: str = "general",
        languages: list[str] | None = None,
        frameworks: list[str] | None = None,
    ) -> None:
        # 使用 Worker 角色
        super().__init__(agent_id=agent_id, role=AgentRole.WORKER, message_bus=message_bus)
        self.llm_config = llm_config
        self.workdir = workdir
        self.domain = domain
        self.languages = languages or ["python"]
        self.frameworks = frameworks or []
        self._engine: AgentEngine | None = None
        self._submissions: list[CodeSubmission] = []
        self._semantic_validator = SemanticValidator(llm_config)

    def _get_engine(self) -> AgentEngine:
        """获取 AgentEngine"""
        if self._engine is None:
            self._engine = create_agent_engine(
                workdir=self.workdir,
            )
        return self._engine

    @property
    def expertise(self) -> CodeExpertise:
        """获取专家能力"""
        return CodeExpertise(
            domain=self.domain,
            languages=self.languages,
            frameworks=self.frameworks,
            confidence=0.8,
        )

    async def implement(
        self,
        task_description: str,
        architecture_plan: str = "",
        constraints: list[str] | None = None,
    ) -> CodeSubmission:
        """实现代码

        参数:
            task_description: 任务描述
            architecture_plan: 架构规划
            constraints: 约束条件

        返回:
            CodeSubmission 对象
        """
        engine = self._get_engine()

        prompt = f"""作为 {self.domain} 领域的专家程序员，请实现以下功能:

任务: {task_description}
"""
        if architecture_plan:
            prompt += f"\n架构规划:\n{architecture_plan}\n"

        if constraints:
            prompt += "\n约束条件:\n" + "\n".join(f"- {c}" for c in constraints) + "\n"

        prompt += """
请输出:
1. 完整的代码实现
2. 测试用例
3. 实现说明

代码请使用 ```python 代码块格式。"""

        session = await engine.run(prompt)
        result = session.final_result

        # 提取代码
        code = self._extract_code(result)

        submission = CodeSubmission(
            submission_id=f"submission-{int(time.time())}",
            coder_id=self.agent_id,
            code=code,
            file_path=f"{self.domain}_{int(time.time())}.py",
            domain=self.domain,
            explanation=result,
        )

        self._submissions.append(submission)

        # 自我校验
        validation = await self._semantic_validator.validate(
            code, submission.file_path
        )

        if validation["passed"]:
            logger.info(f"Coder {self.agent_id}: 代码自我校验通过")
        else:
            logger.warning(f"Coder {self.agent_id}: 代码自我校验失败: {validation['critical_failures']}")

        return submission

    async def review_code(self, code: str, file_path: str) -> Vote:
        """审查代码 — Coder 也可以审查其他人的代码

        返回:
            Vote 对象
        """
        engine = self._get_engine()

        prompt = f"""作为 {self.domain} 领域的专家，请审查以下代码:

文件: {file_path}

代码:
```python
{code}
```

请评估:
1. 代码质量 (1-10)
2. 是否存在问题
3. 改进建议

最后请投票: APPROVE (批准), REJECT (驳回), 或 ABSTAIN (弃权)
并给出置信度 (0.0-1.0)。"""

        session = await engine.run(prompt)
        result = session.final_result.lower()

        # 解析投票
        if "approve" in result:
            vote_type = VoteType.APPROVE
        elif "reject" in result:
            vote_type = VoteType.REJECT
        else:
            vote_type = VoteType.ABSTAIN

        # 提取置信度 (简单解析)
        confidence = 0.5
        import re
        match = re.search(r'(\d+\.?\d*)\s*%', result)
        if match:
            confidence = float(match.group(1)) / 100
        elif re.search(r'[89]|10', result):
            confidence = 0.8

        return Vote(
            voter_id=self.agent_id,
            vote_type=vote_type,
            confidence=confidence,
            reasoning=result[:500],
        )

    async def fix_code(
        self,
        original_code: str,
        feedback: str,
        file_path: str = "",
    ) -> CodeSubmission:
        """根据反馈修复代码

        参数:
            original_code: 原始代码
            feedback: 审计/审查反馈
            file_path: 文件路径

        返回:
            CodeSubmission 对象
        """
        engine = self._get_engine()

        prompt = f"""请根据以下反馈修复代码:

原始代码:
```python
{original_code}
```

反馈:
{feedback}

请输出修复后的完整代码。"""

        session = await engine.run(prompt)
        result = session.final_result

        code = self._extract_code(result)

        submission = CodeSubmission(
            submission_id=f"fix-{int(time.time())}",
            coder_id=self.agent_id,
            code=code,
            file_path=file_path or f"fix_{int(time.time())}.py",
            domain=self.domain,
            explanation=f"修复反馈: {feedback[:200]}",
        )

        self._submissions.append(submission)
        return submission

    def _extract_code(self, text: str) -> str:
        """从文本中提取代码"""
        import re
        matches = re.findall(r'```python\n(.*?)\n```', text, re.DOTALL)
        if matches:
            return matches[0]
        return text

    async def process(self, message: AgentMessage) -> str:
        """处理消息"""
        if message.message_type == MessageType.TASK_ASSIGN:
            # 任务分配: 实现代码
            task_desc = message.content
            submission = await self.implement(task_desc)
            return f"代码实现完成: {submission.submission_id}"

        elif message.message_type == MessageType.REVIEW_REQUEST:
            # 代码审查请求
            code = message.content
            vote = await self.review_code(code, "review.py")
            return f"审查完成: {vote.vote_type.value} (置信度: {vote.confidence:.2f})"

        elif message.message_type == MessageType.AUDIT_REQUEST:
            # 审计请求 (作为反馈修复)
            code = message.content
            submission = await self.fix_code(code, "需要修复审计问题")
            return f"代码修复完成: {submission.submission_id}"

        return f"未知消息类型: {message.message_type}"

    def get_submissions(self) -> list[CodeSubmission]:
        """获取所有提交"""
        return self._submissions.copy()

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "domain": self.domain,
            "submissions": len(self._submissions),
            "languages": self.languages,
        }
