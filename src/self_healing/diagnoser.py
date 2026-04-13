"""AI 诊断器 — 使用 LLM 进行根因诊断"""
from __future__ import annotations

import logging
from typing import Any

from ..agent.engine import AgentEngine
from ..agent.factory import create_agent_engine
from ..llm import LLMConfig

logger = logging.getLogger(__name__)

DIAGNOSIS_PROMPT_TEMPLATE = """你是一个专业的代码诊断专家。请分析以下错误并提供修复方案。

## 错误信息
{error}

## 上下文
{context}

## 任务
1. 分析错误的根因
2. 提供具体的修复方案
3. 如果有多种修复方案，推荐最优的一种

## 输出格式
根因分析: ...
修复方案: ...
修复代码:
```python
# 修复后的代码
```
"""


class AIDiagnoser:
    """AI 诊断器

    使用 LLM 对未知错误进行根因诊断。
    """

    def __init__(self, llm_config: LLMConfig | None = None) -> None:
        self._llm_config = llm_config
        self._engine: AgentEngine | None = None

    def _get_engine(self) -> AgentEngine:
        if self._engine is None:
            self._engine = create_agent_engine(
                provider_type=self._llm_config.provider.value if self._llm_config else 'openai',
                api_key=self._llm_config.api_key if self._llm_config else '',
                model=self._llm_config.model if self._llm_config else 'gpt-4o',
            )
        return self._engine

    async def diagnose(
        self,
        error: str,
        context: dict[str, Any] | None = None,
        active_exploration: bool = True,
    ) -> dict[str, str]:
        """诊断错误根因 (v0.66: 支持主动探索)

        参数:
            error: 错误消息
            context: 错误上下文
            active_exploration: 是否允许 Agent 主动使用工具探索代码库
        """
        context_str = '\n'.join(f'- {k}: {v}' for k, v in (context or {}).items())

        if active_exploration:
            # 模式 1: 主动探索模式 - 给 Agent 充分自由去查代码
            exploration_prompt = f"""作为一个高级代码架构师，你需要诊断并修复以下系统错误。
你可以使用任何可用的工具（如 FileRead, Grep, Glob）来深入了解代码逻辑、依赖关系和潜在的 Bug 来源。

[错误信息]
{error}

[初步上下文]
{context_str}

[目标]
1. 找出错误的根本原因
2. 找到相关的代码文件并阅读它们
3. 提供一个完整的修复方案，包括具体的修复代码
4. 确保修复方案不会引入新的回归问题

请在最后以“根因分析:”、“修复方案:”和“修复代码:”的结构输出。
"""
            try:
                engine = self._get_engine()
                # 开启主动探索模式（God Mode 也可以根据需要开启）
                session = await engine.run(exploration_prompt)
                return self._parse_diagnosis(session.final_result)
            except Exception as e:
                logger.warning(f'主动诊断失败: {e}，回退到基础模式')

        # 模式 2: 基础诊断模式
        prompt = DIAGNOSIS_PROMPT_TEMPLATE.format(error=error, context=context_str)
        try:
            engine = self._get_engine()
            session = await engine.run(prompt)
            return self._parse_diagnosis(session.final_result)
        except Exception as e:
            logger.warning(f'AI 诊断失败: {e}，使用默认诊断结果')
            return {
                'root_cause': f'未知错误: {error}',
                'fix_plan': '建议人工审查',
                'fix_code': '',
            }

    @staticmethod
    def _parse_diagnosis(result: str) -> dict[str, str]:
        """解析诊断结果"""
        import re

        root_cause = ''
        fix_plan = ''
        fix_code = ''

        # 提取根因分析
        rc_match = re.search(r'根因分析[:\s]*(.*?)(?:修复方案|$)', result, re.DOTALL)
        if rc_match:
            root_cause = rc_match.group(1).strip()

        # 提取修复方案
        fp_match = re.search(r'修复方案[:\s]*(.*?)(?:修复代码|$)', result, re.DOTALL)
        if fp_match:
            fix_plan = fp_match.group(1).strip()

        # 提取修复代码
        code_match = re.search(r'```(?:python)?\s*(.*?)\s*```', result, re.DOTALL)
        if code_match:
            fix_code = code_match.group(1)

        return {
            'root_cause': root_cause or result[:200],
            'fix_plan': fix_plan or '建议人工审查',
            'fix_code': fix_code,
        }
