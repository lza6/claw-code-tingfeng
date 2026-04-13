"""经验检索模块 — 从历史经验中检索提示

从 Enterprise LTM 系统中检索历史经验，提供任务执行提示。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def retrieve_experience(goal: str, progress_callback=None) -> list[str]:
    """检索历史经验并返回提示

    参数:
        goal: 任务目标
        progress_callback: 进度回调函数 (agent, message) -> None

    返回:
        历史经验提示列表
    """
    progress = progress_callback or (lambda a, m: logger.info(f'[{a}] {m}'))

    try:
        from .self_fission.rl_experience import RLExperienceHub

        hub = RLExperienceHub()

        # 检索历史最优方案
        best_practices = hub.find_best_practices(goal, top_k=3)

        # 检查高频失败模式
        failure_warnings = hub.get_failure_warnings(goal)

        hints: list[str] = []

        if best_practices:
            for i, exp in enumerate(best_practices, 1):
                hints.append(
                    f"历史方案 {i}: {exp.task_description} -> {exp.solution} "
                    f"(成功率: {exp.success_rate:.0%}, 尝试: {exp.total_attempts})"
                )

        if failure_warnings:
            for warn in failure_warnings[:2]:
                hints.append(
                    f"⚠️ 失败预警: {warn.pattern} (出现 {warn.frequency} 次)"
                )

        progress('rl-exp', f'检索到 {len(hints)} 条历史经验')
        return hints

    except ImportError as e:
        progress('rl-exp', f'经验回传模块未安装: {e}，跳过')
        return []
    except Exception as e:
        progress('rl-exp', f'经验检索失败: {e}，跳过')
        logger.warning(f'经验回传异常: {e}')
        return []
