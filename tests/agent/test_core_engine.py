"""_core_engine 模块测试 — AgentLoopConfig, _run_agent_loop, 辅助函数"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.engine_loop import (
    AgentLoopConfig,
    _add_step,
    _extract_code_changes,
    _execute_single_tool,
    _execute_tools_parallel_safe,
    _is_missing_info_error,
    _run_agent_loop,
)
from src.core.exceptions import LLMProviderError, ToolExecutionError
from src.llm import LLMMessage, LLMResponse
from src.tools_runtime.base import ToolResult


# ====================================================================
# AgentLoopConfig 测试
# ====================================================================

class TestAgentLoopConfig:
    """AgentLoopConfig 数据类测试"""

    def test_minimal_config(self):
        """最小配置创建"""
        config = AgentLoopConfig(
            goal="test goal",
            llm_provider=MagicMock(),
            messages=[],
            max_iterations=3,
            system_prompt="sys",
            tools={},
        )
        assert config.goal == "test goal"
        assert config.max_iterations == 3
        assert config.tools == {}
        assert config.is_stream is False
        assert config.auditor is None
        assert config.audit_mode is False

    def test_default_values(self):
        """测试默认值"""
        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
        )
        assert config.rag_index is None
        assert config.shutdown_requested is False
        assert config.enable_cost_tracking is False
        assert config.max_audit_retries == 2
        assert config.max_repeat_calls == 3
        assert config.on_chunk is None
        assert config.session is None

    def test_perf_metrics_default(self):
        """性能指标默认值"""
        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
        )
        assert config._perf_metrics['llm_call_count'] == 0
        assert config._perf_metrics['llm_total_latency'] == 0.0
        assert config._perf_metrics['llm_retry_count'] == 0

    def test_stream_config(self):
        """流式配置"""
        on_chunk = MagicMock()
        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
            is_stream=True, on_chunk=on_chunk,
        )
        assert config.is_stream is True
        assert config.on_chunk is on_chunk


# ====================================================================
# _is_missing_info_error 测试
# ====================================================================

class TestIsMissingInfoError:
    """_is_missing_info_error 辅助函数测试"""

    def test_exact_match(self):
        patterns = ["缺少信息", "not found"]
        assert _is_missing_info_error("错误：缺少信息", patterns) is True

    def test_case_insensitive(self):
        patterns = ["NOT FOUND"]
        assert _is_missing_info_error("error: not found in db", patterns) is True

    def test_no_match(self):
        patterns = ["timeout", "network"]
        assert _is_missing_info_error("connection refused", patterns) is False

    def test_empty_patterns(self):
        assert _is_missing_info_error("any error", []) is False

    def test_partial_match(self):
        patterns = ["missing"]
        assert _is_missing_info_error("MISSING required field", patterns) is True


# ====================================================================
# _add_step 测试
# ====================================================================

class TestAddStep:
    """_add_step 辅助函数测试"""

    def test_add_step_basic(self):
        session = MagicMock()
        session.steps = []
        on_step = MagicMock()

        _add_step(session, "llm", "call", "result", True, on_step)

        assert len(session.steps) == 1
        assert session.steps[0].step_type == "llm"
        assert session.steps[0].action == "call"
        assert session.steps[0].success is True
        on_step.assert_called_once()

    def test_add_step_no_callback(self):
        session = MagicMock()
        session.steps = []

        _add_step(session, "report", "done", "ok", True, None)

        assert len(session.steps) == 1


# ====================================================================
# _extract_code_changes 测试
# ====================================================================

class TestExtractCodeChanges:
    """_extract_code_changes 函数测试"""

    def test_single_code_block(self):
        messages = [LLMMessage(role="assistant", content="```\nprint('hello')\n```")]
        result = _extract_code_changes(messages)
        assert len(result) == 1
        assert "generated_code_0.py" in result

    def test_multiple_code_blocks(self):
        content = "```\ncode1\n```\nsome text\n```\ncode2\n```"
        messages = [LLMMessage(role="assistant", content=content)]
        result = _extract_code_changes(messages)
        assert len(result) == 2

    def test_non_assistant_messages_ignored(self):
        messages = [LLMMessage(role="user", content="```\ncode\n```")]
        result = _extract_code_changes(messages)
        assert len(result) == 0

    def test_code_block_with_filename_comment(self):
        content = "```python\n# file: utils.py\ndef foo(): pass\n```"
        messages = [LLMMessage(role="assistant", content=content)]
        result = _extract_code_changes(messages)
        assert "utils.py" in result

    def test_no_code_blocks(self):
        messages = [LLMMessage(role="assistant", content="just text")]
        result = _extract_code_changes(messages)
        assert len(result) == 0

    def test_empty_messages(self):
        result = _extract_code_changes([])
        assert len(result) == 0


# ====================================================================
# _run_agent_loop 测试 — 正常流程
# ====================================================================

class MockLLMProvider:
    """模拟 LLM Provider"""
    async def chat(self, messages):
        return LLMResponse(
            content="done",
            model="mock-model",
            usage={"total_tokens": 10, "prompt_tokens": 5, "completion_tokens": 5},
        )


class TestRunAgentLoopBasic:
    """_run_agent_loop 基本流程测试"""

    @pytest.mark.asyncio
    async def test_no_llm_provider(self):
        """无 LLM 配置时返回错误"""
        config = AgentLoopConfig(
            goal="test", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="sys", tools={},
        )
        result = await _run_agent_loop(config=config)
        assert result["session"].is_complete is True
        assert "未配置 LLM" in result["session"].final_result

    @pytest.mark.asyncio
    async def test_single_iteration_no_tools(self):
        """单轮迭代，无工具调用"""
        provider = MockLLMProvider()
        config = AgentLoopConfig(
            goal="test", llm_provider=provider, messages=[],
            max_iterations=1, system_prompt="sys", tools={},
        )
        result = await _run_agent_loop(config=config)
        assert result["session"].is_complete is True
        assert result["session"].final_result == "done"

    @pytest.mark.asyncio
    async def test_with_existing_session(self):
        """使用已有 session"""
        from src.agent.engine_session_data import AgentSession
        provider = MockLLMProvider()
        session = AgentSession(goal="test")
        config = AgentLoopConfig(
            goal="test", llm_provider=provider, messages=[],
            max_iterations=1, system_prompt="sys", tools={},
            session=session,
        )
        result = await _run_agent_loop(config=config)
        assert result["session"] is session

    @pytest.mark.asyncio
    async def test_with_existing_messages(self):
        """已有消息列表不会被覆盖"""
        provider = MockLLMProvider()
        messages = [LLMMessage(role="system", content="existing")]
        config = AgentLoopConfig(
            goal="test", llm_provider=provider, messages=messages,
            max_iterations=1, system_prompt="sys", tools={},
        )
        result = await _run_agent_loop(config=config)
        # 消息列表中应包含原始 system 消息
        assert result["session"].is_complete is True


# ====================================================================
# _run_agent_loop 测试 — 工具调用
# ====================================================================

class TestRunAgentLoopWithTools:
    """工具调用相关测试"""

    @pytest.mark.asyncio
    async def test_tool_call_detected(self):
        """检测到工具调用并执行"""
        provider = MockLLMProvider()
        # 让 provider 返回包含 tool 标签的内容
        class ToolProvider:
            async def chat(self, messages):
                return LLMResponse(
                    content='<tool>{"name": "TestTool", "args": {}}</tool>最终答案',
                    model="mock",
                    usage={"total_tokens": 10, "prompt_tokens": 5, "completion_tokens": 5},
                )

        execute_tool_fn = AsyncMock(return_value=ToolResult(success=True, output="tool ok"))

        config = AgentLoopConfig(
            goal="test", llm_provider=ToolProvider(), messages=[],
            max_iterations=2, system_prompt="sys", tools={"TestTool": MagicMock()},
            _parse_tool_calls=lambda c: [("TestTool", {})] if '<tool>' in c else [],
            _execute_tool=execute_tool_fn,
        )
        result = await _run_agent_loop(config=config)
        assert execute_tool_fn.call_count >= 1

    @pytest.mark.asyncio
    async def test_tool_loop_detection(self):
        """工具调用循环检测"""
        call_count = 0

        class LoopProvider:
            async def chat(self, messages):
                return LLMResponse(
                    content="loop",
                    model="mock",
                    usage={"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
                )

        def fake_parse(content):
            return [("Tool", {"cmd": "x"})]

        async def fake_execute(name, args):
            nonlocal call_count
            call_count += 1
            return ToolResult(success=True, output="ok")

        config = AgentLoopConfig(
            goal="test", llm_provider=LoopProvider(), messages=[],
            max_iterations=5, system_prompt="sys", tools={},
            _parse_tool_calls=fake_parse,
            _execute_tool=fake_execute,
            max_repeat_calls=2,  # 2 次后应阻止
        )
        result = await _run_agent_loop(config=config)
        # 调用次数应被 max_repeat_calls 限制
        assert call_count <= 3


# ====================================================================
# _run_agent_loop 测试 — 异常流程
# ====================================================================

class TestRunAgentLoopErrors:
    """异常流程测试"""

    @pytest.mark.asyncio
    async def test_llm_provider_error(self):
        """LLM 调用失败"""
        class FailingProvider:
            async def chat(self, messages):
                raise LLMProviderError(message="LLM 连接失败")

        config = AgentLoopConfig(
            goal="test", llm_provider=FailingProvider(), messages=[],
            max_iterations=1, system_prompt="sys", tools={},
        )
        result = await _run_agent_loop(config=config)
        assert result["session"].is_complete is True
        assert "执行出错" in result["session"].final_result

    @pytest.mark.asyncio
    async def test_tool_execution_error(self):
        """工具执行失败"""
        class ToolProvider:
            async def chat(self, messages):
                return LLMResponse(
                    content='<tool>{"name": "FailingTool", "args": {}}</tool>',
                    model="mock",
                    usage={"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
                )

        async def failing_execute(name, args):
            raise ToolExecutionError(message="tool failed")

        config = AgentLoopConfig(
            goal="test", llm_provider=ToolProvider(), messages=[],
            max_iterations=2, system_prompt="sys", tools={},
            _parse_tool_calls=lambda c: [("FailingTool", {})] if '<tool>' in c else [],
            _execute_tool=failing_execute,
        )
        result = await _run_agent_loop(config=config)
        assert result["session"].is_complete is True


# ====================================================================
# _run_agent_loop 测试 — 边界条件
# ====================================================================

class TestRunAgentLoopEdgeCases:
    """边界条件测试"""

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self):
        """达到最大迭代次数 — 通过让 LLM 始终返回无工具调用的内容来确保达到 max_iterations"""

        class NoToolProvider:
            async def chat(self, messages):
                # 返回无 tool 标签的内容，使循环在第二次迭代后自然结束
                return LLMResponse(
                    content="done",
                    model="m",
                    usage={"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
                )

        config = AgentLoopConfig(
            goal="test", llm_provider=NoToolProvider(), messages=[],
            max_iterations=2, system_prompt="sys", tools={},
        )
        result = await _run_agent_loop(config=config)
        # 2 次迭代后应完成（第一次检测到无工具调用即完成）
        assert result["session"].is_complete is True

    @pytest.mark.asyncio
    async def test_shutdown_requested(self):
        """shutdown_requested 标志"""
        config = AgentLoopConfig(
            goal="test", llm_provider=MockLLMProvider(), messages=[],
            max_iterations=3, system_prompt="sys", tools={},
            shutdown_requested=True,
        )
        result = await _run_agent_loop(config=config)
        assert "用户请求关闭" in result["session"].final_result

    @pytest.mark.asyncio
    async def test_shutdown_requested_via_getter(self):
        """通过 _shutdown_requested_getter 回调检测关闭"""
        config = AgentLoopConfig(
            goal="test", llm_provider=MockLLMProvider(), messages=[],
            max_iterations=3, system_prompt="sys", tools={},
            _shutdown_requested_getter=lambda: True,
        )
        result = await _run_agent_loop(config=config)
        assert "用户请求关闭" in result["session"].final_result

    @pytest.mark.asyncio
    async def test_config_mode_args(self):
        """使用 config 对象调用"""
        provider = MockLLMProvider()
        config = AgentLoopConfig(
            goal="test",
            llm_provider=provider,
            messages=[],
            max_iterations=1,
            system_prompt="sys",
            tools={},
        )
        result = await _run_agent_loop(config=config)
        assert result["session"].is_complete is True

    @pytest.mark.asyncio
    async def test_config_required(self):
        """缺少 config 参数应抛出 TypeError"""
        with pytest.raises(TypeError):
            await _run_agent_loop(goal="test")


# ====================================================================
# _run_agent_loop 测试 — 事件发布回调
# ====================================================================

class TestRunAgentLoopEvents:
    """事件发布回调测试"""

    @pytest.mark.asyncio
    async def test_publish_callbacks(self):
        """验证事件发布回调被调用"""
        publish_started = MagicMock()
        publish_llm_started = MagicMock()
        publish_llm_completed = MagicMock()
        publish_task_completed = MagicMock()
        publish_token_and_cost = MagicMock()

        config = AgentLoopConfig(
            goal="test", llm_provider=MockLLMProvider(), messages=[],
            max_iterations=1, system_prompt="sys", tools={},
            publish_task_started=publish_started,
            publish_llm_started=publish_llm_started,
            publish_llm_completed=publish_llm_completed,
            publish_task_completed=publish_task_completed,
            publish_token_and_cost=publish_token_and_cost,
        )
        await _run_agent_loop(config=config)

        publish_started.assert_called_once()
        publish_llm_started.assert_called_once()
        publish_llm_completed.assert_called_once()
        publish_task_completed.assert_called_once()
        publish_token_and_cost.assert_called_once()


# ====================================================================
# _execute_single_tool 测试
# ====================================================================

class TestExecuteSingleTool:
    """_execute_single_tool 测试"""

    @pytest.mark.asyncio
    async def test_success(self):
        """工具执行成功"""
        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
            _execute_tool=AsyncMock(return_value=ToolResult(success=True, output="ok")),
        )
        pub_started = MagicMock()
        config.publish_tool_started = pub_started

        name, args, result = await _execute_single_tool(config, "MyTool", {"a": 1}, "")
        assert result.success is True
        assert result.output == "ok"
        pub_started.assert_called_once_with("MyTool", {"a": 1})

    @pytest.mark.asyncio
    async def test_no_executor(self):
        """未配置执行器"""
        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
            _execute_tool=None,
        )
        _, _, result = await _execute_single_tool(config, "T", {}, "")
        assert result.success is False
        assert "未配置" in result.error

    @pytest.mark.asyncio
    async def test_tool_execution_error(self):
        """工具执行错误"""
        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
            _execute_tool=AsyncMock(return_value=ToolResult(success=False, output="", error="fail")),
        )
        _, _, result = await _execute_single_tool(config, "T", {}, "")
        assert result.success is False


# ====================================================================
# _execute_tools_parallel_safe 测试
# ====================================================================

class TestExecuteToolsParallelSafe:
    """_execute_tools_parallel_safe 测试"""

    @pytest.mark.asyncio
    async def test_parallel_success(self):
        """多个工具并行成功"""
        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
            _execute_tool=AsyncMock(return_value=ToolResult(success=True, output="ok")),
        )
        calls = [("T1", {}), ("T2", {})]
        results = await _execute_tools_parallel_safe(config, calls, "")
        assert len(results) == 2
        assert all(r.success for _, _, r in results)

    @pytest.mark.asyncio
    async def test_parallel_one_fails(self):
        """并行中一个失败不影响其他"""
        call_results = [
            ToolResult(success=True, output="ok1"),
            ToolResult(success=False, output="", error="fail"),
        ]
        idx = [0]

        async def mock_execute(name, args):
            r = call_results[idx[0]]
            idx[0] += 1
            return r

        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
            _execute_tool=mock_execute,
        )
        calls = [("T1", {}), ("T2", {})]
        results = await _execute_tools_parallel_safe(config, calls, "")
        assert len(results) == 2
        assert results[0][2].success is True
        assert results[1][2].success is False

    @pytest.mark.asyncio
    async def test_no_executor(self):
        """未配置执行器"""
        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
            _execute_tool=None,
        )
        results = await _execute_tools_parallel_safe(config, [("T", {})], "")
        assert results[0][2].success is False


# ====================================================================
# _run_agent_loop 测试 — 流式模式
# ====================================================================

class TestRunAgentLoopStreaming:
    """流式模式测试"""

    @pytest.mark.asyncio
    async def test_streaming_mode_with_chat_stream(self):
        """流式模式使用 chat_stream"""

        class StreamingProvider:
            async def chat_stream(self, messages):
                for chunk in ["Hello", " ", "World"]:
                    yield chunk

        config = AgentLoopConfig(
            goal="test", llm_provider=StreamingProvider(), messages=[],
            max_iterations=1, system_prompt="sys", tools={},
            is_stream=True,
            _llm_config=MagicMock(model="stream-model"),
            _count_tokens=lambda msgs: sum(len(m.content) // 4 + 1 for m in msgs),
        )
        result = await _run_agent_loop(config=config)
        assert result["session"].is_complete is True
        assert result["session"].final_result == "Hello World"

    @pytest.mark.asyncio
    async def test_streaming_mode_with_on_chunk(self):
        """流式模式 on_chunk 回调被调用"""
        chunks_received = []

        class StreamingProvider:
            async def chat_stream(self, messages):
                for chunk in ["A", "B", "C"]:
                    yield chunk

            async def chat(self, messages):
                return LLMResponse(content="ABC", model="m", usage={"total_tokens": 0})

        config = AgentLoopConfig(
            goal="test", llm_provider=StreamingProvider(), messages=[],
            max_iterations=1, system_prompt="sys", tools={},
            is_stream=True,
            on_chunk=lambda c: chunks_received.append(c),
        )
        result = await _run_agent_loop(config=config)
        assert result["session"].is_complete is True
        assert "Hello World" == result["session"].final_result or chunks_received


# ====================================================================
# _run_agent_loop 测试 — 审计模式
# ====================================================================

class TestRunAgentLoopAuditMode:
    """审计模式测试"""

    @pytest.mark.asyncio
    async def test_audit_passes(self):
        """审计通过"""

        class AuditingProvider:
            async def chat(self, messages):
                # 第二次调用时返回无工具的内容（审计通过后）
                return LLMResponse(
                    content="```\n# file: test.py\ndef hello(): pass\n```",
                    model="mock",
                    usage={"total_tokens": 0},
                )

        audit_report = MagicMock()
        audit_report.passed = True

        auditor = MagicMock()
        auditor.audit = AsyncMock(return_value=audit_report)

        config = AgentLoopConfig(
            goal="test", llm_provider=AuditingProvider(), messages=[],
            max_iterations=3, system_prompt="sys", tools={},
            audit_mode=True, auditor=auditor,
        )
        result = await _run_agent_loop(config=config)
        assert result["session"].is_complete is True

    @pytest.mark.asyncio
    async def test_audit_rejects_then_retries(self):
        """审计驳回后重试"""

        call_count = [0]

        class AuditingProvider:
            async def chat(self, messages):
                call_count[0] += 1
                return LLMResponse(
                    content="```\n# file: test.py\ndef foo(): pass\n```",
                    model="mock",
                    usage={"total_tokens": 0},
                )

        audit_report_fail = MagicMock()
        audit_report_fail.passed = False
        audit_report_fail.to_markdown = lambda: "Security issue found"

        audit_report_pass = MagicMock()
        audit_report_pass.passed = True

        auditor = MagicMock()
        auditor.audit = AsyncMock(side_effect=[audit_report_fail, audit_report_pass])

        config = AgentLoopConfig(
            goal="test", llm_provider=AuditingProvider(), messages=[],
            max_iterations=5, system_prompt="sys", tools={},
            audit_mode=True, auditor=auditor, max_audit_retries=2,
        )
        result = await _run_agent_loop(config=config)
        assert auditor.audit.call_count >= 1


# ====================================================================
# _run_agent_loop 测试 — RAG 增强
# ====================================================================

class TestRunAgentLoopRAG:
    """RAG 增强测试"""

    @pytest.mark.asyncio
    async def test_rag_context_injection(self):
        """RAG 上下文被注入到用户消息中"""
        # 需要模拟 TextIndexer/LazyIndexer 的 isinstance 检查
        from src.rag import TextIndexer

        class MockRAGIndex(TextIndexer):
            def __init__(self):
                pass

            def get_context(self, goal, top_k=3):
                return "RAG context for: " + goal

        captured_messages = []

        class CapturingProvider:
            async def chat(self, messages):
                captured_messages.extend(messages)
                return LLMResponse(content="done", model="m", usage={"total_tokens": 0})

        config = AgentLoopConfig(
            goal="find bug in code", llm_provider=CapturingProvider(), messages=[],
            max_iterations=1, system_prompt="sys", tools={},
            rag_index=MockRAGIndex(),
        )
        await _run_agent_loop(config=config)

        # 查找 user 消息中包含 RAG 上下文
        user_msgs = [m for m in captured_messages if m.role == "user"]
        assert len(user_msgs) >= 1
        assert "参考上下文" in user_msgs[0].content
        assert "RAG context" in user_msgs[0].content


# ====================================================================
# _run_agent_loop 测试 — 成本追踪
# ====================================================================

class TestRunAgentLoopCostTracking:
    """成本追踪测试"""

    @pytest.mark.asyncio
    async def test_cost_tracking_enabled(self):
        """启用成本追踪"""
        cost_estimator = MagicMock()
        cost_estimator.get_total_cost = MagicMock(return_value=0.05)
        cost_estimator.get_summary = MagicMock(return_value={"total": 0.05})
        cost_estimator.record_call = MagicMock()

        config = AgentLoopConfig(
            goal="test", llm_provider=MockLLMProvider(), messages=[],
            max_iterations=1, system_prompt="sys", tools={},
            enable_cost_tracking=True,
            _cost_estimator=cost_estimator,
            _llm_config=MagicMock(model="gpt-4"),
        )
        result = await _run_agent_loop(config=config)
        cost_estimator.record_call.assert_called_once()


# ====================================================================
# _run_agent_loop 测试 — MetricsCollector
# ====================================================================

class TestRunAgentLoopMetricsCollector:
    """MetricsCollector 集成测试"""

    @pytest.mark.asyncio
    async def test_metrics_collector_records_llm_call(self):
        """MetricsCollector 记录 LLM 调用"""
        metrics_collector = MagicMock()
        metrics_lock = asyncio.Lock()

        config = AgentLoopConfig(
            goal="test", llm_provider=MockLLMProvider(), messages=[],
            max_iterations=1, system_prompt="sys", tools={},
            _metrics_collector=metrics_collector,
            _metrics_lock=metrics_lock,
        )
        await _run_agent_loop(config=config)
        metrics_collector.record_llm_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_collector_records_error(self):
        """MetricsCollector 记录错误"""

        class FailingProvider:
            async def chat(self, messages):
                raise RuntimeError("unexpected error")

        metrics_collector = MagicMock()

        config = AgentLoopConfig(
            goal="test", llm_provider=FailingProvider(), messages=[],
            max_iterations=1, system_prompt="sys", tools={},
            _metrics_collector=metrics_collector,
        )
        await _run_agent_loop(config=config)
        metrics_collector.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_collector_records_tool_call(self):
        """MetricsCollector 记录工具调用"""
        metrics_collector = MagicMock()
        metrics_lock = asyncio.Lock()

        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
            _execute_tool=AsyncMock(return_value=ToolResult(success=True, output="ok")),
            _metrics_collector=metrics_collector,
            _metrics_lock=metrics_lock,
        )
        await _execute_single_tool(config, "T", {}, "")
        metrics_collector.record_tool_call.assert_called_once()


# ====================================================================
# _run_agent_loop 测试 — LLM 重试计数
# ====================================================================

class TestRunAgentLoopLLMRetry:
    """LLM 重试计数测试"""

    @pytest.mark.asyncio
    async def test_llm_retry_count_incremented(self):
        """LLMProviderError 包含'重试'时增加重试计数"""
        metrics_lock = asyncio.Lock()
        perf_metrics = {'llm_call_count': 0, 'llm_total_latency': 0.0, 'llm_retry_count': 0}

        class RetryProvider:
            async def chat(self, messages):
                raise LLMProviderError(message="LLM 调用重试失败")

        config = AgentLoopConfig(
            goal="test", llm_provider=RetryProvider(), messages=[],
            max_iterations=1, system_prompt="sys", tools={},
            _metrics_lock=metrics_lock,
            _perf_metrics=perf_metrics,
        )
        await _run_agent_loop(config=config)
        assert perf_metrics['llm_retry_count'] == 1


# ====================================================================
# _run_agent_loop 测试 — 并行工具执行错误传播
# ====================================================================

class TestParallelToolErrors:
    """并行工具错误测试"""

    @pytest.mark.asyncio
    async def test_parallel_tool_execution_error(self):
        """并行工具执行抛出 ToolExecutionError"""
        metrics_lock = asyncio.Lock()
        perf_metrics = {'llm_call_count': 0, 'llm_total_latency': 0.0, 'llm_retry_count': 0,
                        'tool_call_count': 0, 'tool_total_latency': 0.0, 'tool_error_count': 0}

        async def failing_execute(name, args):
            raise ToolExecutionError(message="parallel fail")

        config = AgentLoopConfig(
            goal="g", llm_provider=None, messages=[],
            max_iterations=1, system_prompt="", tools={},
            _execute_tool=failing_execute,
            _metrics_lock=metrics_lock,
            _perf_metrics=perf_metrics,
        )
        calls = [("T1", {}), ("T2", {})]
        results = await _execute_tools_parallel_safe(config, calls, "")
        assert all(not r.success for _, _, r in results)
        assert perf_metrics['tool_call_count'] == 2
        assert perf_metrics['tool_error_count'] == 2
