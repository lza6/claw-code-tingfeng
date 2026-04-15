"""Unified agent core engine

This module merges the duplicate logic from engine.run() and agent_stream.run_stream()
into a single `_run_agent_loop()` coroutine that accepts a `stream` flag and optional
`on_chunk` callback.  This eliminates ~80% code duplication while preserving backward
compatibility through the original `run()` and `run_stream()` methods in engine.py.

Enhancements (v0.27+):
- Error recovery with retry logic for transient errors
- Provider failover for LLM failures
- Checkpoint save/restore
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.exceptions import LLMProviderError, ToolExecutionError
from ..llm import LLMMessage, LLMResponse
from ..utils import debug, error, info, warn


@dataclass
class AgentLoopConfig:
    """Agent 循环配置对象 - 封装 30+ 个参数为结构化配置"""

    # 核心配置
    goal: str
    llm_provider: Any
    messages: list[LLMMessage]
    max_iterations: int
    system_prompt: str
    tools: dict

    # 可选配置（带默认值）
    rag_index: Any | None = None
    world_model: Any | None = None  # 新增: WorldModel 支持
    shutdown_requested: bool = False
    _shutdown_requested_getter: Callable[[], bool] | None = None
    _llm_config: Any = None
    enable_cost_tracking: bool = False
    _cost_estimator: Any = None
    _perf_metrics: dict[str, Any] = field(default_factory=lambda: {
        'llm_call_count': 0,
        'llm_total_latency': 0.0,
        'llm_retry_count': 0,
    })
    _metrics_lock: Any = None
    _truncator: Any = None
    _parse_tool_calls: Callable[[str], list[tuple[str, dict[str, Any]]]] | None = None
    _execute_tool: Callable[[str, dict[str, Any]], Any] | None = None
    _count_tokens: Callable[[list[LLMMessage]], int] | None = None
    _missing_info_patterns: list[str] | None = None
    _deep_rag_patch: Callable[[list[dict]], Any] | None = None
    max_repeat_calls: int = 3

    # 审计配置
    auditor: Any | None = None
    audit_mode: bool = False
    max_audit_retries: int = 2

    # 任务追踪器 (用于 RUF006)
    _background_tasks: set[asyncio.Task] = field(default_factory=set)

    # Reflection 循环 (借鉴 Aider)
    max_reflections: int = 3
    reflection_message: str | None = None  # 外部注入的 reflection 消息

    # 流式配置
    is_stream: bool = False
    on_chunk: Callable[[str], None] | None = None

    # 自愈引擎
    healing_engine: Any | None = None

    # 事件发布器
    publish_llm_started: Callable[[int, int], None] | None = None
    publish_llm_completed: Callable[[int, str, dict], None] | None = None
    publish_tool_started: Callable[[str, dict], None] | None = None
    publish_tool_completed: Callable[[str, dict, Any], None] | None = None
    publish_task_started: Callable[[str, int], None] | None = None
    publish_task_completed: Callable[[str, str, int, int], None] | None = None
    publish_task_error: Callable[[str, str, str | None, int], None] | None = None
    publish_token_and_cost: Callable[[int, dict | None], None] | None = None

    # 回调和会话
    on_step: Callable[[Any, Any], None] | None = None
    session: Any | None = None
    _metrics_collector: Any | None = None
    patcher: Any | None = None


async def _run_agent_loop(
    *,
    config: AgentLoopConfig,
) -> dict[str, Any]:
    """Unified agent loop — works for both blocking and streaming modes.

    Args:
        config: AgentLoopConfig 封装所有循环参数

    Returns a dict with:
        session: AgentSession (new or provided)
        full_content: last LLM response text
    """

    from .engine_session_data import AgentSession, AgentStep

    _shutdown = config.shutdown_requested
    if config._shutdown_requested_getter:
        _shutdown = config._shutdown_requested_getter()

    session_new = config.session is None
    if session_new:
        config.session = AgentSession(goal=config.goal)

    tool_call_history: list[tuple[str, str]] = []
    mode_tag = '[流式]' if config.is_stream else ''

    if config.publish_task_started:
        config.publish_task_started(config.goal, config.max_iterations)

    if config.llm_provider is None:
        error('LLM 提供商未配置')
        _add_step(config.session, 'report', '未配置 LLM 提供商',
                  '请先配置 LLM API key 和模型', False, config.on_step)
        config.session.is_complete = True
        config.session.final_result = '错误：未配置 LLM 提供商'
        return {'session': config.session}

    # RAG context enhancement (first turn only)
    rag_context = ''
    if config.rag_index:
        try:
            from ..rag import LazyIndexer, TextIndexer
            if isinstance(config.rag_index, (TextIndexer, LazyIndexer)):
                rag_context = config.rag_index.get_context(config.goal, top_k=3)
        except ImportError:
            pass

    user_content = f'任务目标：{config.goal}'
    if rag_context:
        user_content += f'\n\n## 参考上下文\n\n{rag_context}'
    user_content += '\n\n请开始执行。'

    if not config.messages:
        config.messages = [
            LLMMessage(role='system', content=config.system_prompt),
            LLMMessage(role='user', content=user_content),
        ]

    _audit_retry_count = 0
    _reflection_count = 0

    for iteration in range(config.max_iterations):
        if _shutdown or (config._shutdown_requested_getter and config._shutdown_requested_getter()):
            warn('用户请求关闭，提前终止代理循环')
            config.session.final_result = '用户请求关闭，任务已终止。'
            config.session.is_complete = True
            break

        # Truncate messages
        if config._truncator:
            config.messages = await config._truncator.truncate_messages(config.messages)

        try:
            mode_tag = '[流式]' if config.is_stream else ''
            debug(f'{mode_tag} 第 {iteration + 1}/{config.max_iterations} 轮迭代')

            llm_step = AgentStep(
                step_type='llm',
                action=f'第 {iteration + 1}/{config.max_iterations} 轮{"流式" if config.is_stream else ""}调用',
                result='流式生成中...' if config.is_stream else '调用中...',
                success=False,
            )
            if config.on_step:
                config.on_step(llm_step, config.session)

            if config.publish_llm_started:
                config.publish_llm_started(iteration + 1, len(config.messages))

            # --- LLM call ---------------------------------------------------
            full_content = ''
            try:
                _llm_start = time.monotonic()

                if config.is_stream and hasattr(config.llm_provider, 'chat_stream'):
                    async for chunk in config.llm_provider.chat_stream(messages=config.messages):
                        full_content += chunk
                        if config.on_chunk:
                            config.on_chunk(chunk)
                    _llm_latency = time.monotonic() - _llm_start
                    # 流式模式精确 token 计数
                    if config._count_tokens:
                        output_tokens = config._count_tokens([LLMMessage(role='assistant', content=full_content)])
                        input_tokens = config._count_tokens(config.messages)
                    else:
                        output_tokens = 0
                        input_tokens = 0
                    response = LLMResponse(
                        content=full_content,
                        model=config._llm_config.model if config._llm_config else 'unknown',
                        usage={
                            'total_tokens': input_tokens + output_tokens,
                            'prompt_tokens': input_tokens,
                            'completion_tokens': output_tokens,
                        },
                    )
                else:
                    # 非流式模式
                    response = await config.llm_provider.chat(messages=config.messages)
                    _llm_latency = time.monotonic() - _llm_start
                    full_content = response.content

                if config._metrics_lock:
                    async with config._metrics_lock:
                        config._perf_metrics['llm_call_count'] += 1
                        config._perf_metrics['llm_total_latency'] += _llm_latency

                # MetricsCollector 记录
                if config._metrics_collector is not None:
                    llm_tokens = response.usage.get('total_tokens', 0) if response.usage else 0
                    llm_input = response.usage.get('prompt_tokens', 0) if response.usage else 0
                    llm_output = response.usage.get('completion_tokens', 0) if response.usage else 0
                    llm_cost = 0.0
                    if config.enable_cost_tracking and config._cost_estimator:
                        llm_cost = config._cost_estimator.get_total_cost()
                    config._metrics_collector.record_llm_call(
                        latency=_llm_latency,
                        total_tokens=llm_tokens,
                        input_tokens=llm_input,
                        output_tokens=llm_output,
                        model=config._llm_config.model if config._llm_config else 'unknown',
                        success=True,
                        cost=llm_cost,
                    )

            except LLMProviderError as e:
                if config._metrics_lock and ('重试' in str(e) or 'retry' in str(e).lower()):
                    async with config._metrics_lock:
                        config._perf_metrics['llm_retry_count'] += 1
                raise
            except Exception as e:
                raise LLMProviderError(
                    message=f'LLM {"流式" if config.is_stream else ""}调用失败: {e}',
                    details={'model': config._llm_config.model if config._llm_config else 'unknown'},
                ) from e

            # Cost tracking
            config.session.total_tokens += response.usage.get('total_tokens', 0)

            if config.publish_llm_completed:
                config.publish_llm_completed(iteration + 1, response.model, response.usage)

            if config.enable_cost_tracking and response.usage and config._cost_estimator:
                model_name = response.model or (config._llm_config.model if config._llm_config else 'unknown')
                input_tokens = response.usage.get('prompt_tokens', 0) or response.usage.get('input_tokens', 0)
                output_tokens = response.usage.get('completion_tokens', 0) or response.usage.get('output_tokens', 0)
                # 获取增强的 tokens (v0.19.0)
                cache_read = response.usage.get('cache_read_tokens', 0)
                cache_write = response.usage.get('cache_write_tokens', 0)
                reasoning = response.usage.get('reasoning_tokens', 0)

                label_suffix = 'stream_call' if config.is_stream else 'call'
                config._cost_estimator.record_call(
                    model=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=cache_write,
                    reasoning_tokens=reasoning,
                    label=f'llm_{label_suffix}_{iteration + 1}',
                )

            llm_step = AgentStep(
                step_type='llm',
                action=f'第 {iteration + 1}/{config.max_iterations} 轮{"流式" if config.is_stream else ""}调用',
                result=full_content[:200], success=True,
            )
            if config.on_step:
                config.on_step(llm_step, config.session)

            config.messages.append(LLMMessage(role='assistant', content=full_content))

            # --- Tool calls -------------------------------------------------
            if config._parse_tool_calls:
                tool_calls = config._parse_tool_calls(full_content)
            else:
                tool_calls = []
            if tool_calls:
                info(f'{mode_tag} 检测到 {len(tool_calls)} 个工具调用')

                # 过滤循环
                valid_calls: list[tuple[str, dict[str, Any]]] = []
                loop_warnings: list[str] = []
                for tool_name, tool_args in tool_calls:
                    call_signature = (tool_name, json.dumps(tool_args, sort_keys=True))
                    repeat_count = tool_call_history.count(call_signature)
                    if repeat_count >= config.max_repeat_calls:
                        warn(f'{mode_tag} 检测到重复工具调用: {tool_name} (已调用 {repeat_count + 1} 次)')
                        loop_warnings.append(
                            f'你已重复调用 {tool_name} 相同参数 {repeat_count + 1} 次。'
                            f'请换一种方法或直接给出最终答案。'
                        )
                        continue
                    tool_call_history.append(call_signature)
                    valid_calls.append((tool_name, tool_args))

                # 并行执行多个工具（当 >1 个调用时使用 asyncio.gather）
                if len(valid_calls) > 1 and config._execute_tool is not None:
                    # 检查是否涉及文件修改，如果涉及则开启事务
                    file_ops = [args.get('file_path') for name, args in valid_calls if 'FileEdit' in name and args.get('file_path')]
                    if file_ops and config.patcher:
                        from pathlib import Path
                        await config.patcher.begin_transaction([Path(p) for p in file_ops])

                    try:
                        results = await _execute_tools_parallel_safe(
                            config, valid_calls, mode_tag
                        )
                        # 如果任何一个失败，理论上在工具内部逻辑可能已经写盘，但这里提供顶层事务提交/回滚机会
                        # 实际上单工具失败目前不触发全量回滚，除非明确逻辑要求。
                        # 这里先做 commit，因为 _execute_tools_parallel_safe 内部独立处理结果。
                        if config.patcher:
                            config.patcher.commit()
                    except Exception as e:
                        if config.patcher:
                            config.patcher.rollback()

                        # 触发自愈逻辑
                        if config.healing_engine:
                            debug(f"{mode_tag} 并行执行工具出错，触发自愈: {e}")
                            # 尝试对第一个失败的工具或整体错误进行自愈
                            await config.healing_engine.heal(e)

                        raise e
                else:
                    results = []
                    for tool_name, tool_args in valid_calls:
                        # 单工具执行的事务保护
                        is_file_edit = 'FileEdit' in tool_name and tool_args.get('file_path')
                        if is_file_edit and config.patcher:
                            from pathlib import Path
                            await config.patcher.begin_transaction([Path(tool_args['file_path'])])

                        try:
                            result = await _execute_single_tool(
                                config, tool_name, tool_args, mode_tag
                            )
                            # 如果执行失败，回滚并尝试自愈
                            if is_file_edit and config.patcher:
                                _res_obj = result[2] if isinstance(result, tuple) else result
                                if not _res_obj.success:
                                    config.patcher.rollback()
                                    if config.healing_engine:
                                        debug(f"{mode_tag} 工具执行失败，触发自愈: {_res_obj.error}")
                                        # 传入上下文
                                        await config.healing_engine.heal(
                                            error=_res_obj.error or _res_obj.output,
                                            context={
                                                "tool_name": tool_name,
                                                "tool_args": tool_args,
                                                "file_path": tool_args.get("file_path"),
                                                "code": tool_args.get("content") or tool_args.get("new_string"),
                                            }
                                        )
                                else:
                                    config.patcher.commit()

                            results.append((tool_name, tool_args, result))
                        except Exception as e:
                            if is_file_edit and config.patcher:
                                config.patcher.rollback()
                            if config.healing_engine:
                                debug(f"{mode_tag} 单工具执行崩溃，触发自愈: {e}")
                                await config.healing_engine.heal(e, context={"tool_name": tool_name, "tool_args": tool_args})
                            raise e

                for tool_name, tool_args, result in results:
                    if config.publish_tool_completed:
                        config.publish_tool_completed(tool_name, tool_args, result)

                    # --- WorldModel 预取 (v0.65) ---
                    # 当工具成功读取或编辑文件时，触发 topologically 相关文件的预取
                    # result 可能是一个 ToolResult 对象或一个元组 (name, args, result)
                    _res_obj = result[2] if isinstance(result, tuple) else result
                    if getattr(_res_obj, 'success', False) and config.world_model:
                        file_path = tool_args.get('file_path')
                        if file_path:
                            debug(f'{mode_tag} 触发 WorldModel 预取: {file_path}')
                            # 异步触发，不阻塞主循环
                            import asyncio
                            task = asyncio.create_task(config.world_model.prefetch_context(file_path))
                            config._background_tasks.add(task)
                            task.add_done_callback(config._background_tasks.discard)

                    # 错误 RAG 补丁
                    rag_patch = None
                    if not _res_obj.success and config._missing_info_patterns and config._deep_rag_patch:
                        error_text = _res_obj.error or _res_obj.output
                        if _is_missing_info_error(error_text, config._missing_info_patterns):
                            debug(f'{mode_tag} 检测到"缺少信息"错误，触发 RAG 补丁')
                            rag_patch = await config._deep_rag_patch([{
                                'tool': tool_name, 'args': tool_args, 'error': _res_obj.output,
                            }])

                    # 构建结果消息
                    content_parts = [f'工具 {tool_name} 执行结果：\n{_res_obj.output}']
                    if rag_patch:
                        content_parts.append(f'\n\n## 补充参考资料\n\n{rag_patch}\n\n请利用以上资料重新尝试。')

                    config.messages.append(LLMMessage(role='user', content='\n'.join(content_parts)))
                    step = AgentStep(step_type='execute', action=f'{tool_name}({tool_args})',
                                     result=_res_obj.output, success=_res_obj.success)
                    config.session.steps.append(step)
                    if config.on_step:
                        config.on_step(step, config.session)

                    if _res_obj.success:
                        debug(f'{mode_tag} 工具 {tool_name} 执行成功')
                    else:
                        warn(f'{mode_tag} 工具 {tool_name} 执行失败: {_res_obj.error}')

                # 注入循环警告
                if loop_warnings:
                    config.messages.append(LLMMessage(role='user', content='\n'.join(loop_warnings)))

            else:
                # --- No tool calls → task complete or report ----------------
                # Audit mode
                if config.audit_mode and config.auditor and _audit_retry_count < config.max_audit_retries:
                    code_changes = _extract_code_changes(config.messages)
                    if code_changes:
                        audit_report = await config.auditor.audit(code_changes)
                        if not audit_report.passed:
                            _audit_retry_count += 1
                            warn(f'代码审计驳回 ({_audit_retry_count}/{config.max_audit_retries})')
                            config.messages.append(LLMMessage(
                                role='user',
                                content=f'代码审计驳回，请修复以下问题:\n\n{audit_report.to_markdown()}\n\n请重新提交。',
                            ))
                            step = AgentStep(step_type='audit', action='代码审计驳回',
                                             result=audit_report.to_markdown(), success=False)
                            config.session.steps.append(step)
                            if config.on_step:
                                config.on_step(step, config.session)
                            continue

                # Reflection 循环 (借鉴 Aider): 如果外部注入了 reflection 消息，回传给 LLM
                if (config.reflection_message
                        and _reflection_count < config.max_reflections
                        and iteration + 1 < config.max_iterations):
                    _reflection_count += 1
                    debug(f'{mode_tag} Reflection {_reflection_count}/{config.max_reflections}')
                    config.messages.append(LLMMessage(
                        role='user',
                        content=config.reflection_message,
                    ))
                    config.reflection_message = None  # 消费掉
                    step = AgentStep(
                        step_type='reflect',
                        action=f'自我修正 {_reflection_count}/{config.max_reflections}',
                        result=config.messages[-1].content[:200],
                        success=True,
                    )
                    config.session.steps.append(step)
                    if config.on_step:
                        config.on_step(step, config.session)
                    continue

                info(f'{mode_tag} 任务完成')
                config.session.is_complete = True
                config.session.final_result = response.content if isinstance(response, LLMResponse) else full_content
                step = AgentStep(step_type='report', action='完成任务',
                                 result=response.content if isinstance(response, LLMResponse) else full_content, success=True)
                config.session.steps.append(step)
                if config.on_step:
                    config.on_step(step, config.session)
                if config.publish_task_completed:
                    config.publish_task_completed(config.session.goal, config.session.final_result, config.session.total_tokens, len(config.session.steps))
                break

        except (LLMProviderError, ToolExecutionError) as e:
            error_code = e.code.value if hasattr(e, 'code') and hasattr(e.code, 'value') else None
            err_msg = getattr(e, 'message', str(e))
            error(f'{mode_tag} 代理执行出错: [{error_code}] {err_msg}')
            if config._metrics_collector is not None:
                config._metrics_collector.record_error(type(e).__name__)
            step = AgentStep(step_type='report', action='错误', result=str(e), success=False)
            config.session.steps.append(step)
            if config.on_step:
                config.on_step(step, config.session)
            config.session.is_complete = True
            config.session.final_result = f'执行出错：{err_msg}'
            if config.publish_task_error:
                config.publish_task_error(config.session.goal, str(e), error_code, config.session.total_tokens)
            break
        except Exception as e:
            error(f'{mode_tag} 代理执行出错: {e}')
            if config._metrics_collector is not None:
                config._metrics_collector.record_error(type(e).__name__)
            step = AgentStep(step_type='report', action='错误', result=str(e), success=False)
            config.session.steps.append(step)
            if config.on_step:
                config.on_step(step, config.session)
            config.session.is_complete = True
            config.session.final_result = f'执行出错：{e!s}'
            if config.publish_task_error:
                config.publish_task_error(config.session.goal, str(e), None, config.session.total_tokens)
            break

    if not config.session.is_complete:
        warn(f'{mode_tag} 达到最大迭代次数')
        config.session.is_complete = True
        config.session.final_result = '达到最大迭代次数，任务可能未完成。'

    # Token/cost update
    cost_summary = None
    if config.enable_cost_tracking and config._cost_estimator:
        cost_summary = config._cost_estimator.get_summary()
    if config.publish_token_and_cost:
        config.publish_token_and_cost(config.session.total_tokens, cost_summary)

    info(f'{mode_tag} 任务完成，总消耗 token: {config.session.total_tokens}')
    return {'session': config.session, 'messages': config.messages, 'tool_call_history': tool_call_history}


def _add_step(session: Any, step_type: str, action: str, result: str, success: bool,
              on_step: Callable[[Any, Any], None] | None) -> None:
    """便捷函数 — 添加步骤记录"""
    from .engine_session_data import AgentStep
    step = AgentStep(step_type=step_type, action=action, result=result, success=success)
    session.steps.append(step)
    if on_step:
        on_step(step, session)


def _is_missing_info_error(error_output: str, patterns: list[str]) -> bool:
    """判断错误是否因为缺少信息"""
    error_lower = error_output.lower()
    return any(p.lower() in error_lower for p in patterns)


async def _execute_single_tool(
    config: AgentLoopConfig,
    tool_name: str,
    tool_args: dict[str, Any],
    mode_tag: str,
) -> tuple[str, dict[str, Any], Any]:
    """执行单个工具并记录指标"""
    from ..tools_runtime.base import ToolResult

    if config.publish_tool_started:
        config.publish_tool_started(tool_name, tool_args)

    try:
        _tool_start = time.monotonic()
        if config._execute_tool:
            result = await config._execute_tool(tool_name, tool_args)
        else:
            result = ToolResult(success=False, output='', error='工具执行器未配置')
        _tool_latency = time.monotonic() - _tool_start

        if config._metrics_collector is not None:
            config._metrics_collector.record_tool_call(
                tool_name=tool_name,
                latency=_tool_latency,
                success=result.success,
            )
        if config._metrics_lock:
            async with config._metrics_lock:
                config._perf_metrics.setdefault('tool_call_count', 0)
                config._perf_metrics.setdefault('tool_total_latency', 0.0)
                config._perf_metrics.setdefault('tool_error_count', 0)
                config._perf_metrics['tool_call_count'] += 1
                config._perf_metrics['tool_total_latency'] += _tool_latency
                if not result.success:
                    config._perf_metrics['tool_error_count'] += 1
    except ToolExecutionError as e:
        if config._metrics_lock:
            async with config._metrics_lock:
                config._perf_metrics.setdefault('tool_call_count', 0)
                config._perf_metrics.setdefault('tool_error_count', 0)
                config._perf_metrics['tool_call_count'] += 1
                config._perf_metrics['tool_error_count'] += 1
        if config._metrics_collector is not None:
            config._metrics_collector.record_tool_call(
                tool_name=tool_name,
                latency=time.monotonic() - _tool_start,
                success=False,
            )
        result = ToolResult(success=False, output='', error=str(e))

    return tool_name, tool_args, result


async def _execute_tools_parallel_safe(
    config: AgentLoopConfig,
    valid_calls: list[tuple[str, dict[str, Any]]],
    mode_tag: str,
) -> list[tuple[str, dict[str, Any], Any]]:
    """使用 asyncio.gather 并行执行多个工具"""
    import asyncio

    from ..tools_runtime.base import ToolResult

    results_with_metadata: list[tuple[str, dict[str, Any], Any]] = [
        (name, args, ToolResult(success=False, output='', error='未执行'))
        for name, args in valid_calls
    ]

    async def _run_one(idx: int, tool_name: str, tool_args: dict[str, Any]) -> None:
        if config.publish_tool_started:
            config.publish_tool_started(tool_name, tool_args)

        try:
            _tool_start = time.monotonic()
            if config._execute_tool:
                result = await config._execute_tool(tool_name, tool_args)
            else:
                result = ToolResult(success=False, output='', error='工具执行器未配置')
            _tool_latency = time.monotonic() - _tool_start

            if config._metrics_collector is not None:
                config._metrics_collector.record_tool_call(
                    tool_name=tool_name,
                    latency=_tool_latency,
                    success=result.success,
                )
            if config._metrics_lock:
                async with config._metrics_lock:
                    config._perf_metrics.setdefault('tool_call_count', 0)
                    config._perf_metrics.setdefault('tool_total_latency', 0.0)
                    config._perf_metrics.setdefault('tool_error_count', 0)
                    config._perf_metrics['tool_call_count'] += 1
                    config._perf_metrics['tool_total_latency'] += _tool_latency
                    if not result.success:
                        config._perf_metrics['tool_error_count'] += 1

            results_with_metadata[idx] = (tool_name, tool_args, result)
        except ToolExecutionError as e:
            if config._metrics_lock:
                async with config._metrics_lock:
                    config._perf_metrics.setdefault('tool_call_count', 0)
                    config._perf_metrics.setdefault('tool_error_count', 0)
                    config._perf_metrics['tool_call_count'] += 1
                    config._perf_metrics['tool_error_count'] += 1
            if config._metrics_collector is not None:
                config._metrics_collector.record_tool_call(
                    tool_name=tool_name,
                    latency=time.monotonic() - _tool_start,
                    success=False,
                )
            results_with_metadata[idx] = (tool_name, tool_args, ToolResult(
                success=False, output='', error=str(e)
            ))

    await asyncio.gather(*[
        _run_one(i, name, args) for i, (name, args) in enumerate(valid_calls)
    ])
    return results_with_metadata


def _extract_code_changes(messages: list[LLMMessage]) -> dict[str, str]:
    """从消息历史中提取代码变更"""
    code_changes: dict[str, str] = {}
    for msg in messages:
        if msg.role != 'assistant':
            continue
        code_blocks = re.findall(r'```(?:\w+)?\s*\n(.*?)(?:\n)?```', msg.content, re.DOTALL)
        if code_blocks:
            for i, code in enumerate(code_blocks):
                filename = f'generated_code_{len(code_changes) + i}.py'
                first_line_match = re.match(r'#\s*(?:file|filename|path|文件)[:\s]+(.+)', code, re.IGNORECASE)
                if first_line_match:
                    filename = first_line_match.group(1).strip()
                code_changes[filename] = code
    return code_changes


__all__ = ['_run_agent_loop']
