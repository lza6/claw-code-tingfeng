"""修复策略模式 — 消除硬编码字符串匹配

将 WorkflowEngine._execute_task 中的硬编码字符串匹配重构为策略模式，
提高可维护性和可扩展性。
"""
from __future__ import annotations

import ast
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .models import WorkflowTask


@dataclass
class StrategyContext:
    """策略执行上下文"""
    task: WorkflowTask
    workdir: Path


class FixStrategy(ABC):
    """修复策略基类"""

    @abstractmethod
    def can_handle(self, context: StrategyContext) -> bool:
        """判断是否能处理当前任务"""
        ...

    @abstractmethod
    def execute(self, context: StrategyContext) -> str:
        """执行修复策略"""
        ...


class LongFunctionStrategy(FixStrategy):
    """处理过长函数的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        title_lower = context.task.title.lower()
        desc_lower = context.task.description.lower()
        return any(kw in title_lower or kw in desc_lower for kw in ['long function', '过长'])

    def execute(self, context: StrategyContext) -> str:
        file_info = _parse_file_location(context.task.description)
        if not file_info:
            return '无法定位文件，需要人工确认'

        file_path = context.workdir / file_info['file']
        if not file_path.exists():
            return f'文件不存在: {file_info["file"]}'

        try:
            content = file_path.read_text(encoding='utf-8')
            tree = ast.parse(content)
        except (SyntaxError, OSError):
            return f'无法解析文件: {file_info["file"]}'

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = file_info.get('hint', '')
                if func_name and node.name == func_name:
                    break
        return '已分析长函数，建议人工拆分'


class DeepNestingStrategy(FixStrategy):
    """处理嵌套过深的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        title_lower = context.task.title.lower()
        desc_lower = context.task.description.lower()
        return any(kw in title_lower or kw in desc_lower for kw in ['deep nesting', '嵌套过深'])

    def execute(self, context: StrategyContext) -> str:
        return '嵌套过深问题已记录，建议使用早返回/提取函数/卫语句重构'


class ImportStarStrategy(FixStrategy):
    """处理 import * 的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        return 'import *' in context.task.title.lower()

    def execute(self, context: StrategyContext) -> str:
        file_info = _parse_file_location(context.task.description)
        if not file_info:
            return '无法定位文件'

        file_path = context.workdir / file_info['file']
        if not file_path.exists():
            return f'文件不存在: {file_info["file"]}'

        try:
            file_path.read_text(encoding='utf-8')
        except OSError:
            return '无法读取文件'

        if '__init__.py' in file_info['file']:
            return '忽略 __init__.py 中的 import * (常见包导出模式)'

        return '已识别 import * 问题，建议改为显式导入'


class BareExceptStrategy(FixStrategy):
    """处理 bare except 的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        return 'bare except' in context.task.title.lower()

    def execute(self, context: StrategyContext) -> str:
        return '已识别 bare except，建议改为 except Exception:'


class LongLinesStrategy(FixStrategy):
    """处理超长行的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        title_lower = context.task.title.lower()
        desc_lower = context.task.description.lower()
        return any(kw in title_lower or kw in desc_lower for kw in ['long line', '行过长'])

    def execute(self, context: StrategyContext) -> str:
        return '已识别超长行，建议使用 black/autopep8 格式化'


class EvalExecStrategy(FixStrategy):
    """处理 eval/exec 安全问题的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        title_lower = context.task.title.lower()
        return 'eval' in title_lower or 'exec' in title_lower

    def execute(self, context: StrategyContext) -> str:
        return '标记为安全审查项 — eval/exec 需要人工确认用途'


class DuplicationStrategy(FixStrategy):
    """处理重复代码的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        title_lower = context.task.title.lower()
        desc_lower = context.task.description.lower()
        return any(kw in title_lower or kw in desc_lower for kw in ['repeated', '重复', 'duplicat'])

    def execute(self, context: StrategyContext) -> str:
        return '标记为待重构 — 重复代码需要人工确认公共抽象'


class TooManyParamsStrategy(FixStrategy):
    """处理参数过多的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        title_lower = context.task.title.lower()
        desc_lower = context.task.description.lower()
        return any(kw in title_lower or kw in desc_lower for kw in ['too many parameters', '参数过多'])

    def execute(self, context: StrategyContext) -> str:
        return '标记为待重构 — 参数过多需要封装为 dataclass'


class TooManyMethodsStrategy(FixStrategy):
    """处理类方法过多的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        title_lower = context.task.title.lower()
        desc_lower = context.task.description.lower()
        return 'class' in title_lower and any(kw in title_lower or kw in desc_lower for kw in ['too many', '过多'])

    def execute(self, context: StrategyContext) -> str:
        return '标记为待重构 — 类过大需要人工拆分'


class TodoFixmeStrategy(FixStrategy):
    """处理 TODO/FIXME 的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        title_lower = context.task.title.lower()
        return 'todo' in title_lower or 'fixme' in title_lower

    def execute(self, context: StrategyContext) -> str:
        return '已记录 TODO/FIXME 项，需要人工处理'


class TestCoverageStrategy(FixStrategy):
    """处理测试覆盖率的策略"""

    def can_handle(self, context: StrategyContext) -> bool:
        title_lower = context.task.title.lower()
        return 'test' in title_lower and 'coverage' in title_lower

    def execute(self, context: StrategyContext) -> str:
        return '已识别无测试覆盖，建议使用 LLM 生成测试'


class DefaultStrategy(FixStrategy):
    """默认策略 — 记录问题待人工处理"""

    def can_handle(self, context: StrategyContext) -> bool:
        return True  # 始终可以处理（作为兜底）

    def execute(self, context: StrategyContext) -> str:
        return f'已记录修复建议，待人工执行: {context.task.description}'


class AutoFixStrategy(FixStrategy):
    """[v0.50.0] 自动修复策略 — 能够自动生成代码并应用补丁"""

    def can_handle(self, context: StrategyContext) -> bool:
        # 暂时只处理简单的文档和测试补齐
        title_lower = context.task.title.lower()
        return any(kw in title_lower for kw in ['test gap', 'doc gap', '测试缺口', '文档缺口'])

    def execute(self, context: StrategyContext) -> str:
        # 集成 SwarmEngine 进行真正的代码补全
        # 在 HealableExecutor 中，如果返回包含 "SWARM_REQUIRED" 的字符串，将优先触发 Swarm
        file_info = _parse_file_location(context.task.description)
        target = file_info['file'] if file_info else "整个项目"

        if 'test' in context.task.title.lower():
            return f"SWARM_REQUIRED: 为 {target} 补齐缺失的单元测试，确保覆盖率达到 80% 以上。"
        if 'doc' in context.task.title.lower():
            return f"SWARM_REQUIRED: 为 {target} 完善文档，包括模块说明、函数 Docstring 和使用示例。"

        return f"SWARM_REQUIRED: 自动修复任务: {context.task.title}"

# 策略注册表
STRATEGIES: list[FixStrategy] = [
    AutoFixStrategy(), # 优先尝试自动修复
    LongFunctionStrategy(),
    DeepNestingStrategy(),
    ImportStarStrategy(),
    BareExceptStrategy(),
    LongLinesStrategy(),
    EvalExecStrategy(),
    DuplicationStrategy(),
    TooManyParamsStrategy(),
    TooManyMethodsStrategy(),
    TodoFixmeStrategy(),
    TestCoverageStrategy(),
    DefaultStrategy(),  # 必须放在最后作为兜底
]


def _parse_file_location(desc: str) -> dict[str, str] | None:
    """从描述中解析文件路径和行号"""
    match = re.search(r'文件:\s*([^\s:]+)(?::(\d+))?', desc)
    if not match:
        return None
    result = {'file': match.group(1)}
    if match.group(2):
        result['line'] = match.group(2)
    func_match = re.search(r'[`「](\w+)[`」]', desc)
    if func_match:
        result['hint'] = func_match.group(1)
    lines_match = re.search(r'(\d+)\s*行', desc)
    if lines_match:
        result['lines'] = lines_match.group(1)
    return result


def find_strategy(task: WorkflowTask, workdir: Path) -> FixStrategy:
    """查找能处理当前任务的策略"""
    context = StrategyContext(task=task, workdir=workdir)
    for strategy in STRATEGIES:
        if strategy.can_handle(context):
            return strategy
    return DefaultStrategy()


def execute_strategy(task: WorkflowTask, workdir: Path) -> str:
    """查找并执行能处理当前任务的策略"""
    strategy = find_strategy(task, workdir)
    context = StrategyContext(task=task, workdir=workdir)
    return strategy.execute(context)
