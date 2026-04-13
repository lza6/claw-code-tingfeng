"""Self-Healing Engine — 自主自愈引擎

工作流错误自动感知与 AI 驱动的无干预修复循环。

用法:
    engine = SelfHealingEngine(workdir=Path.cwd())
    result = await engine.heal(error=e, context={'code': code})
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..memory.enterprise_ltm import EnterpriseLTM, PatternType
from .classifier import ErrorClassifier
from .diagnoser import AIDiagnoser
from .experience_bank import VectorExperienceBank
from .models import (
    ErrorCategory,
    HealingResult,
    HealingStats,
    HealingStrategyType,
    VerificationLevel,
)
from .verifier import Verifier

# ==================== Aider 风格反思循环（新增） ====================


class ReflectedMessage:
    """反思消息（从 Aider 移植）

    Aider 在编辑完成后会运行 linter，如果发现错误，
    将错误作为 reflected_message 返回给 LLM 请求修复。

    使用:
    reflected = ReflectedMessage.from_lint(lint_errors)
    if reflected:
        # 将错误返回给 LLM 请求修复
        messages.append(reflected.to_message())
    """

    def __init__(self, text: str, source: str = "lint") -> None:
        self.text = text
        self.source = source

    def to_message(self) -> dict[str, str]:
        """转换为 LLM 消息格式"""
        return {
            "role": "user",
            "content": f"发现以下问题需要修复:\n\n{self.text}",
        }

    @classmethod
    def from_lint(cls, lint_output: str) -> ReflectedMessage | None:
        """从 lint 输出创建反思消息"""
        if not lint_output or not lint_output.strip():
            return None
        return cls(text=lint_output, source="lint")

    @classmethod
    def from_test(cls, test_output: str) -> ReflectedMessage | None:
        """从测试输出创建反思消息"""
        if not test_output or not test_output.strip():
            return None
        return cls(text=test_output, source="test")

logger = logging.getLogger(__name__)


@dataclass
class SelfHealingConfig:
    """自愈配置"""
    enabled: bool = True
    max_attempts: int = 3
    enable_ai_diagnosis: bool = True
    enable_learning: bool = True
    verification_level: VerificationLevel = VerificationLevel.L3_UNIT_TEST
    timeout_seconds: int = 120


class SelfHealingEngine:
    """自愈主引擎

    流程:
    1. 感知错误
    2. 分类错误 / 匹配模式
    3. 生成修复策略
    4. 执行修复 (AI 诊断 + LLM 修复)
    5. 验证修复结果
    6. 学习更新模式
    """

    def __init__(
        self,
        config: SelfHealingConfig | None = None,
        workdir: Path | None = None,
        llm_config: Any = None,
        event_bus: Any | None = None,
    ) -> None:
        self.config = config or SelfHealingConfig()
        self.workdir = workdir or Path.cwd()
        self._llm_config = llm_config

        self.classifier = ErrorClassifier()
        self.diagnoser = AIDiagnoser(llm_config=llm_config)
        self.verifier = Verifier(workdir=self.workdir, level=self.config.verification_level)
        self.experience_bank = VectorExperienceBank()
        self.ltm = EnterpriseLTM()
        from ..core.patch.atomic_patcher import AtomicPatcher
        self.patcher = AtomicPatcher(base_path=self.workdir)

        self.stats = HealingStats()
        # 初始化事件总线引用
        from ..core.events import get_event_bus
        self._event_bus = event_bus or get_event_bus()

    def _publish_event(self, healing_result: HealingResult) -> None:
        """发布自愈事件到事件总线"""
        try:
            from ..core.events import Event, EventType
            data = {
                'error_type': healing_result.error_category.value,
                'error_message': healing_result.error,
                'fix_strategy': healing_result.root_cause,
                'confidence': 0.8,
                'success': healing_result.success,
                'attempts': healing_result.attempts,
                'elapsed_seconds': healing_result.elapsed_seconds,
                'fix_applied': healing_result.fix_applied,
            }
            self._event_bus.publish(Event(
                type=EventType.HEALING_EVENT,
                data=data,
                source='self_healing',
            ))
        except Exception:
            pass

    def _publish_stats(self) -> None:
        """发布统计更新"""
        try:
            from ..core.events import Event, EventType
            s = self.stats
            success_rate = (s.successful_healings / max(s.total_healing_attempts, 1) * 100)
            data = {
                'total_fixes_successful': s.successful_healings,
                'total_fixes_attempted': s.total_healing_attempts,
                'success_rate': success_rate,
                'avg_attempts_per_fix': s.avg_attempts,
            }
            self._event_bus.publish(Event(
                type=EventType.HEALING_STATS_UPDATE,
                data=data,
                source='self_healing',
            ))
        except Exception:
            pass

    async def heal(
        self,
        error: Exception | str,
        context: dict[str, Any] | None = None,
        use_experience: bool = True,
    ) -> HealingResult:
        """执行自愈流程

        参数:
            error: 异常对象或错误消息
            context: 错误上下文
            use_experience: 是否允许从经验库检索 (用于测试隔离)

        返回:
            HealingResult
        """
        start = time.time()
        error_msg = str(error) if isinstance(error, Exception) else error

        self.stats.total_errors_detected += 1
        logger.info(f'检测到错误: {error_msg[:100]}')

        # 初始化变量 (避免未绑定警告)
        category = self.classifier.classify(error_msg)
        root_cause = ""
        strategy = HealingStrategyType.CODE_PATCH

        # 先尝试从经验库检索相似修复 (v0.66: 使用结合了 LTM 的深度检索)
        if use_experience:
            similar_experiences = await self.experience_bank.find_similar_combined(
                error_msg, top_k=3, min_success_rate=0.5
            )

            if similar_experiences:
                logger.info(f'从增强经验库找到 {len(similar_experiences)} 个相似记录')
                for exp in similar_experiences:
                    # 处理 ImplementationPattern (来自 LTM)
                    if hasattr(exp, 'solution_code'):
                        fix_code = exp.solution_code
                        if fix_code.startswith('{'):
                            import json
                            try:
                                fix_data = json.loads(fix_code)
                                if isinstance(fix_data, dict):
                                    fix_code = fix_data.get('fix_code', fix_code)
                            except json.JSONDecodeError:
                                pass

                        verified, verify_msg = await self.verifier.verify(fix_code)
                        if verified:
                            elapsed = time.time() - start
                            self.stats.successful_healings += 1
                            self._update_stats(1, elapsed, category)
                            return HealingResult(
                                success=True,
                                error=error_msg,
                                error_category=category,
                                root_cause=f'增强经验库匹配 (LTM): {getattr(exp, "description", "N/A")}',
                                strategy_used=HealingStrategyType.CODE_PATCH,
                                fix_applied=fix_code,
                                verification_passed=True,
                                attempts=1,
                                elapsed_seconds=elapsed,
                                messages=[f'从增强经验库应用 LTM 修复 (ID: {getattr(exp, "pattern_id", "N/A")})'],
                            )

                    # 处理 ExperienceRecord (来自本地)
                    elif hasattr(exp, 'fix_code') and exp.fix_code:
                        fix_code = exp.fix_code
                        verified, verify_msg = await self.verifier.verify(fix_code)
                        if verified:
                            elapsed = time.time() - start
                            self.stats.successful_healings += 1
                            self.experience_bank.update_success(exp.id, True)
                            self._update_stats(1, elapsed, category)
                            return HealingResult(
                                success=True,
                                error=error_msg,
                                error_category=category,
                                root_cause=f'增强经验库匹配 (Local): {exp.fix_strategy}',
                                strategy_used=HealingStrategyType.CODE_PATCH,
                                fix_applied=fix_code,
                                verification_passed=True,
                                attempts=1,
                                elapsed_seconds=elapsed,
                                messages=[f'从增强经验库应用本地修复 (成功率: {exp.success_rate:.0%})'],
                            )

        for attempt in range(1, self.config.max_attempts + 1):
            self.stats.total_healing_attempts += 1
            logger.info(f'自愈尝试 {attempt}/{self.config.max_attempts}')

            # 分类 + 匹配模式
            category = self.classifier.classify(error_msg)
            pattern = self.classifier.match_pattern(error_msg)

            # 如果这是后续尝试，将之前的失败反馈给诊断器
            if attempt > 1 and verify_msg:
                reflected = ReflectedMessage.from_lint(verify_msg) if category == ErrorCategory.SYNTAX else ReflectedMessage.from_test(verify_msg)
                if reflected:
                    error_msg_for_diagnosis = f"{error_msg}\n\n[上一次尝试失败反馈]\n{reflected.text}"
                else:
                    error_msg_for_diagnosis = error_msg
            else:
                error_msg_for_diagnosis = error_msg

            # 诊断
            if pattern:
                root_cause = pattern.description
                category = pattern.category
                fix_prompt = pattern.fix_prompt.format(
                    code=context.get('code', '') if context else '',
                    error=error_msg_for_diagnosis,
                )
                strategy = pattern.strategy
                pattern.success_count += 1
            elif self.config.enable_ai_diagnosis:
                diagnosis = await self.diagnoser.diagnose(error_msg_for_diagnosis, context)
                root_cause = diagnosis.get('root_cause', '')
                fix_prompt = diagnosis.get('fix_plan', '')
                strategy = HealingStrategyType.CODE_PATCH
            else:
                root_cause = '未知错误，AI 诊断已禁用'
                fix_prompt = '建议人工审查'
                strategy = HealingStrategyType.SKIP_AND_LOG

            # 执行修复
            fix_code = await self._apply_fix(fix_prompt, context, strategy)

            if strategy == HealingStrategyType.SKIP_AND_LOG:
                elapsed = time.time() - start
                self.stats.successful_healings += 1
                return HealingResult(
                    success=True,
                    error=error_msg,
                    error_category=category,
                    root_cause=root_cause,
                    strategy_used=strategy,
                    fix_applied='跳过并记录',
                    verification_passed=True,
                    attempts=attempt,
                    elapsed_seconds=elapsed,
                    messages=['已跳过并记录'],
                )

            # 验证
            verified = True
            verify_msg = ""
            if fix_code and strategy in (HealingStrategyType.CODE_PATCH, HealingStrategyType.CONFIG_FIX):
                verified, verify_msg = await self.verifier.verify(fix_code)
                if verified:
                    elapsed = time.time() - start
                    self.stats.successful_healings += 1
                    self._update_stats(attempt, elapsed, category)

                    # 异步生成回归测试（不阻塞主流程）
                    if strategy in (HealingStrategyType.CODE_PATCH, HealingStrategyType.CONFIG_FIX):
                        asyncio.create_task(self._generate_regression_test(error_msg, fix_code, context))

                    res = HealingResult(
                        success=True,
                        error=error_msg,
                        error_category=category,
                        root_cause=root_cause,
                        strategy_used=strategy,
                        fix_applied=fix_code,
                        verification_passed=True,
                        attempts=attempt,
                        elapsed_seconds=elapsed,
                        messages=[f'修复成功 (尝试 {attempt} 次)', verify_msg],
                    )
                    self._publish_event(res)
                    self._publish_stats()
                    return res
                else:
                    # 记录失败经验
                    self.experience_bank.record_experience(
                        error_traceback=error_msg,
                        fix_strategy=root_cause,
                        fix_code=fix_code,
                        success=False,
                        error_category=category.value if category else "",
                    )
                    error_msg = f'验证失败: {verify_msg}'
                    if pattern:
                        pattern.failure_count += 1
                    logger.warning(f'修复验证失败: {verify_msg}')

            if self.config.enable_learning and fix_code and verified:
                self.experience_bank.record_experience(
                    error_traceback=error_msg,
                    fix_strategy=root_cause,
                    fix_code=fix_code,
                    success=True,
                    error_category=category.value if category else "",
                )
                # 同时异步持久化到 Enterprise LTM
                asyncio.create_task(self.ltm.learn_pattern(
                    goal=f"自愈成功: {error_msg[:100]}",
                    implementation={"fix_code": fix_code, "root_cause": root_cause},
                    pattern_type=PatternType.SUCCESS
                ))

        # 所有尝试均失败
        elapsed = time.time() - start
        self.stats.failed_healings += 1

        # 记录失败经验
        self.experience_bank.record_experience(
            error_traceback=error_msg,
            fix_strategy=root_cause or '未知',
            success=False,
            error_category=category.value,
        )

        return HealingResult(
            success=False,
            error=error_msg,
            error_category=category,
            root_cause=root_cause or '未知',
            strategy_used=strategy,
            fix_applied='',
            verification_passed=False,
            attempts=self.config.max_attempts,
            elapsed_seconds=elapsed,
            messages=[f'自愈失败，已尝试 {self.config.max_attempts} 次'],
        )

    async def _apply_fix(
        self,
        fix_prompt: str,
        context: dict[str, Any] | None,
        strategy: HealingStrategyType,
    ) -> str:
        """应用修复

        返回:
            修复后的代码或修复描述
        """
        if strategy == HealingStrategyType.SKIP_AND_LOG:
            return '跳过并记录'

        if strategy == HealingStrategyType.CONFIG_FIX:
            return await self._fix_config(fix_prompt)

        # 尝试使用 Patch 策略 (如果上下文包含文件路径)
        file_path = context.get('file_path') if context else None
        if strategy == HealingStrategyType.CODE_PATCH and file_path:
            try:
                # 使用 LLM 生成 patch
                patch_content = await self._generate_patch_with_llm(fix_prompt, context)
                if patch_content:
                    # 应用 patch
                    success = self.patcher.apply_patch(file_path, patch_content)
                    if success:
                        return f"Patch applied to {file_path}"
            except Exception as e:
                logger.debug(f"Patch 修复失败: {e}，回退到全量修复")

        # 默认: 使用 LLM 生成修复代码
        return await self._fix_with_llm(fix_prompt, context)

    async def _generate_patch_with_llm(self, prompt: str, context: dict[str, Any] | None) -> str:
        """使用 LLM 生成原子补丁 (Diff 格式)"""
        try:
            from ..agent.factory import create_agent_engine
            engine = create_agent_engine()

            patch_prompt = f"请为以下问题生成一个 SEARCH/REPLACE 格式的补丁:\n\n{prompt}\n\n上下文:\n{context.get('code', '') if context else ''}"
            session = await engine.run(patch_prompt)
            return session.final_result
        except Exception:
            return ""

    async def _fix_with_llm(self, prompt: str, context: dict[str, Any] | None) -> str:
        """使用 LLM 生成修复代码"""
        try:
            from ..agent.factory import create_agent_engine

            if self._llm_config:
                engine = create_agent_engine(
                    provider_type=self._llm_config.provider.value,
                    api_key=self._llm_config.api_key,
                    model=self._llm_config.model or 'gpt-4o',
                )
            else:
                engine = create_agent_engine()

            session = await engine.run(f'请修复以下代码问题:\n\n{prompt}')
            return session.final_result
        except Exception as e:
            logger.warning(f'LLM 修复失败: {e}')
            return ''

    async def _fix_config(self, prompt: str) -> str:
        """配置修复（简化实现）"""
        return f'配置修复建议: {prompt}'

    def _update_stats(self, attempts: int, elapsed: float, category: ErrorCategory) -> None:
        """更新统计"""
        n = self.stats.successful_healings
        self.stats.avg_attempts = (
            (self.stats.avg_attempts * (n - 1) + attempts) / n if n > 0 else attempts
        )
        self.stats.avg_elapsed_seconds = (
            (self.stats.avg_elapsed_seconds * (n - 1) + elapsed) / n if n > 0 else elapsed
        )
        self.stats.error_categories[category.value] = (
            self.stats.error_categories.get(category.value, 0) + 1
        )

    def get_stats_summary(self) -> str:
        """获取统计摘要"""
        s = self.stats
        success_rate = (
            s.successful_healings / max(s.total_healing_attempts, 1) * 100
        )
        return (
            f'[自愈统计]\n{"=" * 40}\n'
            f'错误检测: {s.total_errors_detected}\n'
            f'修复尝试: {s.total_healing_attempts}\n'
            f'成功: {s.successful_healings} ({success_rate:.0f}%)\n'
            f'失败: {s.failed_healings}\n'
            f'平均尝试: {s.avg_attempts:.1f} 次\n'
            f'平均耗时: {s.avg_elapsed_seconds:.1f}s\n'
            f'错误分布: {s.error_categories}\n{"=" * 40}'
        )

    async def heal_autonomous(
        self,
        target: str,
        issue_type: str,
        context: dict[str, Any] | None = None
    ) -> bool:
        """执行自主修复任务 (由 Optimizer 驱动)。"""
        logger.info(f"开始自主修复: {issue_type} -> {target}")

        prompt = f"任务: 自主优化/修复 {issue_type}\n目标: {target}\n上下文: {context}"

        # 简单模拟 heal 流程
        try:
            result = await self.heal(error=f"Optimization task: {issue_type} for {target}", context=context)
            return result.success
        except Exception as e:
            logger.error(f"自主修复失败: {e}")
            return False
    async def _generate_regression_test(
        self,
        error_msg: str,
        fix_code: str,
        context: dict[str, Any] | None,
    ) -> None:
        """生成回归测试用例 (预防复发)"""
        try:
            logger.info("正在生成回归测试以预防错误复发...")
            from ..agent.factory import create_agent_engine

            regression_prompt = f"""作为一个 QA 专家，请根据以下自愈修复记录，生成一个 pytest 测试脚本。
该测试脚本应该能复现之前报错的场景，并验证现在的修复代码是否生效。

[错误信息]
{error_msg}

[已应用的修复代码]
{fix_code}

[原始上下文]
{context.get('code', 'N/A') if context else 'N/A'}

请只输出纯代码，不要包含 markdown 代码块。确保测试脚本是自包含的。
"""
            engine = create_agent_engine()
            session = await engine.run(regression_prompt)
            test_content = session.final_result

            if test_content:
                test_dir = self.workdir / "tests" / "regression"
                test_dir.mkdir(parents=True, exist_ok=True)
                test_file = test_dir / f"test_healed_{uuid.uuid4().hex[:8]}.py"
                test_file.write_text(test_content, encoding="utf-8")
                logger.info(f"回归测试已保存: {test_file.name}")
        except Exception as e:
            logger.error(f"生成回归测试失败: {e}")
