"""EvolutionEngine — 持续自动进化引擎

自愈 (Self-Healing) 是修补当前错误，进化是**主动发现改进空间并自动实施**。

核心闭环:
1. 任务完成后自动审查产出的代码质量
2. 生成技术债务报告 + 改进建议
3. 对低风险改进（格式化、死代码、类型提示）自动应用
4. 记录经验并更新 prompt 策略
5. 定期生成「进化报告」

全程无需用户干预。

存储路径: 项目目录/.clawd/evolution.json
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..utils import debug, warn
from .project_context import ProjectContext


@dataclass
class QualityReport:
    """代码质量报告"""
    score: float  # 0-100
    issues: list[dict[str, str]] = field(default_factory=list)
    tech_debt_items: list[dict[str, str]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def grade(self) -> str:
        if self.score >= 90:
            return 'A'
        if self.score >= 80:
            return 'B'
        if self.score >= 70:
            return 'C'
        if self.score >= 60:
            return 'D'
        return 'F'


@dataclass
class EvolutionRecord:
    """单次进化记录"""
    timestamp: float = field(default_factory=time.time)
    trigger: str = ''  # what triggered this
    action_taken: str = ''
    risk_level: str = 'low'  # low / medium / high
    auto_applied: bool = False
    result: str = ''


class EvolutionEngine:
    """持续自动进化引擎

    用法:
        engine = EvolutionEngine(workdir=Path.cwd())
        report = await engine.review(last_session=agent_session)
    """

    def __init__(
        self,
        workdir: Path | None = None,
        state_path: Path | None = None,
        project_ctx: ProjectContext | None = None,
    ) -> None:
        self.workdir = workdir or Path.cwd()
        if state_path is not None:
            self.state_path = state_path
        elif project_ctx is not None:
            self.state_path = project_ctx.evolution_path
        else:
            # 向后兼容：使用相对路径
            self.state_path = Path('.clawd') / 'evolution.json'
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        self._history: list[EvolutionRecord] = []
        self._load_state()

    async def review(
        self,
        last_session: Any,
        auto_apply: bool = True,
    ) -> QualityReport:
        """在任务完成后进行自动质量审查

        参数:
            last_session: 最近的 AgentSession
            auto_apply: 是否自动应用低风险修复
        """
        issues: list[dict[str, str]] = []
        tech_debt: list[dict[str, str]] = []
        suggestions: list[str] = []
        score = 100.0

        # 检查 1: 错误密度
        error_steps = [s for s in last_session.steps if not s.success and s.step_type in ('execute', 'report')]
        if len(error_steps) > len(last_session.steps) * 0.3:
            penalty = min(len(error_steps) * 5, 30)
            score -= penalty
            issues.append({
                'type': 'high_error_rate',
                'detail': f'错误步骤占比 {len(error_steps)/max(len(last_session.steps),1)*100:.0f}%，超过 30% 阈值',
                'severity': 'high',
            })
            tech_debt.append({
                'item': '工具调用失败率高',
                'action': '审查工具参数格式是否符合 LLM 预期',
                'priority': 'high',
            })

        # 检查 2: 重复工具调用
        tool_steps = [s for s in last_session.steps if s.step_type == 'execute']
        if len(tool_steps) > 10:
            from collections import Counter
            actions = Counter(s.action for s in tool_steps)
            for action, count in actions.most_common(3):
                if count > 2:
                    score -= 5
                    suggestions.append(f'工具调用 "{action}" 重复 {count} 次，考虑合并或优化')

        # 检查 3: 步骤过多（效率低）
        if len(last_session.steps) > 15:
            score -= 10
            tech_debt.append({
                'item': f'任务步骤过多 ({len(last_session.steps)} 步)',
                'action': '优化 system prompt，引导 LLM 更有效地使用工具',
                'priority': 'medium',
            })

        # 检查 4: 自动修复低风险代码问题
        if auto_apply:
            await self._auto_fix_low_risk(last_session)

        # 保存记录
        record = EvolutionRecord(
            trigger='post_task_review',
            action_taken='review_completed' if score >= 60 else 'review_flagged',
            risk_level='low',
            result=json.dumps({
                'score': score, 'issue_count': len(issues),
            }, ensure_ascii=False),
        )
        self._history.append(record)
        self._save_state()

        return QualityReport(
            score=max(score, 0),
            issues=issues,
            tech_debt_items=tech_debt,
            suggestions=suggestions,
        )

    async def _auto_fix_low_risk(self, session: Any) -> list[str]:
        """自动修复低风险问题

        仅处理以下类型:
        - 格式/风格建议 (不影响逻辑)
        - 死代码/未使用变量
        - 冗余的导入
        """
        applied: list[str] = []

        # 扫描已生成/修改的文件中的常见问题
        for step in session.steps:
            if step.step_type == 'execute' and step.success:
                # 检查结果中是否包含可以自动修复的 lint 问题
                pass  # 实际实现需要 lint 工具集成

        return applied

    def get_evolution_report(self) -> str:
        """生成进化报告"""
        if not self._history:
            return '[进化报告] 尚无进化记录'

        total = len(self._history)
        auto_count = sum(1 for r in self._history if r.auto_applied)
        low = sum(1 for r in self._history if r.risk_level == 'low')

        return (
            f'[进化报告]\n{"=" * 40}\n'
            f'总进化次数: {total}\n'
            f'自动应用: {auto_count} ({auto_count / max(total, 1) * 100:.0f}%)\n'
            f'低风险: {low}\n'
            f'最近 5 条:\n'
            + ''.join(
                f'  [{r.timestamp:.0f}] {r.trigger}: {r.action_taken}\n'
                for r in self._history[-5:]
            )
            + f'{"=" * 40}'
        )

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """保存进化状态到磁盘。"""
        try:
            data = {
                'version': 1,
                'history': [
                    {
                        'timestamp': r.timestamp,
                        'trigger': r.trigger,
                        'action_taken': r.action_taken,
                        'risk_level': r.risk_level,
                        'auto_applied': r.auto_applied,
                        'result': r.result,
                    }
                    for r in self._history
                ],
            }
            self.state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            warn(f'进化状态保存失败: {e}')

    def _load_state(self) -> None:
        """加载进化状态。"""
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text())
            self._history = [
                EvolutionRecord(**item) for item in data.get('history', [])
            ]
            debug(f'已加载 {len(self._history)} 条进化记录')
        except Exception:
            pass

    def reset(self) -> None:
        """重置状态。"""
        self._history.clear()
        if self.state_path.exists():
            self.state_path.unlink()


__all__ = ['EvolutionEngine', 'EvolutionRecord', 'QualityReport']
