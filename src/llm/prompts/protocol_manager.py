"""Protocol Manager - 协议模板管理器

借鉴 GoalX 核心演进逻辑，提供协议驱动的任务指令生成能力。
支持 Jinja2 模板渲染。

包含两个核心功能:
- 渲染主协议 (Master Protocol) -> master.md
- 渲染任务协议 (Task Protocol) -> task.md
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)


class ProtocolManager:
    """协议模板管理器"""

    def __init__(self, templates_dir: Path | None = None):
        if templates_dir is None:
            # 默认路径: src/llm/prompts/
            templates_dir = Path(__file__).parent

        self.templates_dir = templates_dir

        # 主环境: 加载全局模板
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # 任务环境: 加载任务级模板
        task_dir = templates_dir / "task_templates"
        self.task_env: Environment | None = None
        if task_dir.exists():
            self.task_env = Environment(
                loader=FileSystemLoader(str(task_dir)),
                autoescape=select_autoescape(["html", "xml"]),
                trim_blocks=True,
                lstrip_blocks=True,
            )

    def render(self, template_name: str, data: dict[str, Any]) -> str:
        """渲染模板"""
        # 补充默认值
        if "current_time" not in data:
            data["current_time"] = datetime.now().isoformat()

        template = self.env.get_template(template_name)
        return template.render(**data)

    def render_master(self, run_dir: Path, data: dict[str, Any]) -> Path:
        """渲染主协议到运行目录"""
        content = self.render("master.md.j2", data)
        out_path = run_dir / "master.md"
        out_path.write_text(content, encoding="utf-8")
        return out_path

    def render_task_protocol(
        self, run_dir: Path, intent: str, context: dict[str, Any]
    ) -> Path:
        """渲染任务指令到运行目录

        Args:
            run_dir: 当前运行的工作目录
            intent: 意图名称 (deliver, explore, evolve, debate, implement)
            context: 模板渲染上下文

        Returns:
            渲染后的任务指令文件路径
        """
        if not self.task_env:
            raise RuntimeError(f"任务模板目录不存在: {self.templates_dir / 'task_templates'}")

        template_name = f"{intent}.md.j2"

        try:
            # 自动获取意图指导 (如果未提供)
            if "guidance" not in context or not context["guidance"]:
                context["guidance"] = self._get_intent_guidance(intent)

            # 补充默认值
            if "current_time" not in context:
                context["current_time"] = datetime.now().isoformat()

            template = self.task_env.get_template(template_name)
            content = template.render(**context)

            out_path = run_dir / f"task-{intent}.md"
            out_path.write_text(content, encoding="utf-8")
            return out_path
        except Exception as e:
            logger.error(f"渲染任务协议失败 (intent={intent}): {e}")
            fallback_path = run_dir / f"task-{intent}.md"
            fallback_content = f"[{intent.upper()}] {context.get('goal_description', 'Unknown goal')}\n(模板渲染失败: {e!s})"
            fallback_path.write_text(fallback_content, encoding="utf-8")
            return fallback_path

    @staticmethod
    def get_default_data(
        workdir: Path, run_id: str, goal: str, intent: str = "deliver"
    ) -> dict[str, Any]:
        """获取默认的协议数据"""
        run_dir = workdir / ".clawd" / "runs" / run_id
        return {
            "run_name": run_id,
            "objective": goal,
            "intent": intent,
            "project_root": str(workdir),
            "run_worktree_path": str(workdir / ".clawd" / "worktrees"),
            "objective_contract_path": str(run_dir / "objective-contract.json"),
            "obligation_model_path": str(run_dir / "obligation-model.json"),
            "assurance_plan_path": str(run_dir / "assurance-plan.json"),
            "evidence_log_path": str(run_dir / "evidence-log.jsonl"),
            "composition": {
                "enabled": True,
                "philosophy": [
                    "Simplicity First",
                    "Goal-Driven Execution",
                    "Evidence-Based Reasoning",
                ],
            },
        }

    @staticmethod
    def _get_intent_guidance(intent: str) -> str:
        """获取意图指导 (从 intent_routing 引入)"""
        try:
            from ...workflow.intent_routing import Intent, get_intent_guidance

            intent_enum = Intent(intent.lower())
            return get_intent_guidance(intent_enum)
        except Exception:
            # 回退到硬编码指导
            guidances = {
                "deliver": "专注于交付可验证的最终结果。确保所有目标都有证据支持。",
                "explore": "深入调查，收集证据。不急于结论，确保每个发现都有可验证的证据支持。",
                "evolve": "不断寻找下一个最佳改进点。评估每个改进的价值/成本比，优先高价值低成本的改进。",
                "debate": "从批判性角度审视已有结论。寻找弱点，验证假设，确保结论经得起挑战。",
                "implement": "根据之前探索或辩论的结论进行实现。遵循已确定的方案，不重新质疑。",
            }
            return guidances.get(
                intent.lower(), "按照既定目标和要求完成任务。"
            )
