"""推理模式测试（LLM 与工具全部用 fake，不调真实 API）"""
import pytest

from src.reasoning import (
    DebatePattern,
    LATSPattern,
    PlanExecuteLoop,
    ReasoningConfig,
    ReflexionLoop,
    run_reasoning,
)


class FakeLLM:
    """按调用序号返回预设脚本"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, system, user):
        self.calls.append((system, user))
        if not self.script:
            return "{}"
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fake_tools(mapping):
    """tool_executor: name -> observation"""

    def _exec(name, args):
        if name in mapping:
            return mapping[name]
        return f"[工具错误] 未注册工具: {name}"

    return _exec


# ============ Reflexion ============

class TestReflexion:
    def test_success_first_try(self):
        llm = FakeLLM([
            '{"tool": "decompile", "args": {"addr": "0x401000"}, "final": false}',
            '{"tool": null, "final": true, "answer": "函数是 MD5 实现"}',
            '{"confidence": 0.9}',  # self-assess
        ])
        r = ReflexionLoop(llm=llm, tool_executor=fake_tools({"decompile": "push ebp; ..."}))
        result = r.run("分析 0x401000 的算法")
        assert result.answer == "函数是 MD5 实现"
        assert result.confidence == 0.9
        assert result.total_tool_calls == 1
        assert result.pattern == "reflexion"

    def test_reflects_on_tool_error(self):
        llm = FakeLLM([
            # 迭代1: 调不存在的工具
            '{"tool": "wrong_tool", "args": {}, "final": false}',
            # 反思
            '{"what_failed": "wrong_tool", "why": "工具名错误", "next_hypothesis": "用 grep_tool", "avoid": ["wrong_tool"]}',
            # 迭代2: 修正后成功
            '{"tool": "grep_tool", "args": {"q": "md5"}, "final": false}',
            '{"tool": null, "final": true, "answer": "找到 md5"}',
            '{"confidence": 0.7}',
        ])
        r = ReflexionLoop(llm=llm, tool_executor=fake_tools({"grep_tool": "found md5"}))
        result = r.run("找哈希函数")
        assert result.answer == "找到 md5"
        # 反思已写入 steps
        assert any("wrong_tool" in s.reflection or s.reflection for s in result.steps)

    def test_invalid_json_retry(self):
        llm = FakeLLM([
            "这不是JSON",  # 迭代1: 格式错误
            '{"tool": null, "final": true, "answer": "ok"}',
            '{"confidence": 0.5}',
        ])
        r = ReflexionLoop(llm=llm, tool_executor=fake_tools({}))
        result = r.run("任务")
        assert result.answer == "ok"

    def test_max_iterations(self):
        llm = FakeLLM([])  # 永远返回 {} → 无法决策，但 {} 解析后 final=False tool=None → 结束
        r = ReflexionLoop(
            llm=llm, tool_executor=fake_tools({}),
            config=ReasoningConfig(max_iterations=3),
        )
        # {} → tool None → final 分支，answer 为空但正常返回
        result = r.run("任务")
        assert result.pattern == "reflexion"

    def test_tool_call_limit(self):
        llm = FakeLLM([
            '{"tool": "t", "args": {}, "final": false}',
            '{"tool": null, "final": true, "answer": "x"}',
            '{"confidence": 0.5}',
        ])
        r = ReflexionLoop(
            llm=llm, tool_executor=fake_tools({"t": "ok"}),
            config=ReasoningConfig(max_tool_calls=1),
        )
        result = r.run("任务")
        assert result.total_tool_calls == 1


# ============ Plan-Execute ============

class TestPlanExecute:
    def test_full_plan_success(self):
        llm = FakeLLM([
            '{"steps": [{"id": 1, "goal": "列函数", "tool": "list_funcs", "args": {}}, {"id": 2, "goal": "总结", "tool": null}]}',
            "最终结论: 有 5 个函数",  # final
        ])
        r = PlanExecuteLoop(llm=llm, tool_executor=fake_tools({"list_funcs": "main, foo, bar, baz, qux"}))
        result = r.run("统计函数")
        assert result.answer == "最终结论: 有 5 个函数"
        assert result.confidence == 0.8
        assert result.total_tool_calls == 1

    def test_replan_on_tool_failure(self):
        llm = FakeLLM([
            # 第一轮计划：工具失败
            '{"steps": [{"id": 1, "goal": "调试", "tool": "debugger", "args": {}}]}',
            # 第二轮重规划：改用静态分析
            '{"steps": [{"id": 2, "goal": "静态分析", "tool": "strings", "args": {}}]}',
            "最终: 用 strings 找到了",
        ])
        r = PlanExecuteLoop(
            llm=llm,
            tool_executor=fake_tools({"debugger": "[工具错误] 无法附加", "strings": "md5, sha1"}),
        )
        result = r.run("逆向")
        assert "strings 找到" in result.answer or result.answer == "最终: 用 strings 找到了"
        assert result.iterations == 2

    def test_empty_plan(self):
        llm = FakeLLM(['{"steps": []}'])
        r = PlanExecuteLoop(llm=llm, tool_executor=fake_tools({}))
        result = r.run("任务")
        assert result.answer == "计划为空，无法推进"


# ============ LATS ============

class TestLATS:
    def test_branch_and_score(self):
        llm = FakeLLM([
            # 深度1: 生成2个假设
            '{"hypotheses": [{"id": 1, "statement": "是MD5", "verification": {"tool": "check", "args": {"a": 1}}}, {"id": 2, "statement": "是SHA1", "verification": {"tool": "check", "args": {"a": 2}}}]}',
            # 评分
            '{"candidates": [{"id": 1, "score": 0.9, "evidence": "常量匹配"}, {"id": 2, "score": 0.3, "evidence": ""}]}',
            # 深度2 假设
            '{"hypotheses": [{"id": 3, "statement": "确认为MD5", "verification": {"tool": "verify", "args": {}}}]}',
            # 评分2
            '{"candidates": [{"id": 3, "score": 0.95, "evidence": "双重确认"}]}',
            # 最终综合
            "结论: MD5",
        ])
        r = LATSPattern(llm=llm, tool_executor=fake_tools({"check": "ok", "verify": "yes"}), branching=2, depth=2)
        result = r.run("识别算法")
        assert result.answer == "结论: MD5"
        assert result.confidence == 0.95
        assert result.total_tool_calls == 3
        assert result.iterations == 2

    def test_no_hypotheses_breaks(self):
        llm = FakeLLM([
            '{"hypotheses": []}',
            "综合结论",
        ])
        r = LATSPattern(llm=llm, tool_executor=fake_tools({}))
        result = r.run("任务")
        assert result.answer == "综合结论"


# ============ Debate ============

class TestDebate:
    def test_debate_with_revision(self):
        llm = FakeLLM([
            # 质疑 r1（附验证）
            '{"objection": "没有验证调用点", "tool": "xref", "args": {"addr": "0x401000"}}',
            # 辩护 r1（修正结论）
            '{"response": "验证显示无调用", "revised_conclusion": "这是死代码"}',
            # 质疑 r2
            '{"objection": "无", "tool": null}',
            # 辩护 r2
            '{"response": "维持", "revised_conclusion": null}',
        ])
        r = DebatePattern(llm=llm, tool_executor=fake_tools({"xref": "0 refs"}), rounds=2)
        result = r.run("分析函数", conclusion="初步: 这是登录函数")
        assert result.answer == "这是死代码"
        assert result.confidence == 0.65

    def test_debate_generates_own_conclusion(self):
        llm = FakeLLM([
            "自动结论: X",
            '{"objection": "证据不足", "tool": null}',
            '{"response": "补充", "revised_conclusion": "X(已加固)"}',
        ])
        r = DebatePattern(llm=llm, tool_executor=fake_tools({}), rounds=1)
        result = r.run("任务")
        assert result.answer == "X(已加固)"

    def test_invalid_json_stops(self):
        llm = FakeLLM(["初步结论", "坏JSON"])
        r = DebatePattern(llm=llm, tool_executor=fake_tools({}), rounds=2)
        result = r.run("任务")
        assert result.answer == "初步结论"
        assert result.iterations == 1


# ============ 统一入口 ============

class TestRunReasoning:
    def test_dispatch(self):
        llm = FakeLLM([
            '{"tool": null, "final": true, "answer": "done"}',
            '{"confidence": 0.6}',
        ])
        result = run_reasoning("reflexion", "任务", llm=llm, tool_executor=fake_tools({}))
        assert result.answer == "done"

    def test_unknown_pattern(self):
        with pytest.raises(ValueError, match="未知推理模式"):
            run_reasoning("nope", "任务", llm=FakeLLM([]))

    def test_default_tool_executor_from_registry(self):
        """默认 executor 走 clawd ToolRegistry（未注册工具返回错误观察而非抛异常）"""
        llm = FakeLLM([
            '{"tool": "nonexistent_tool", "args": {}, "final": false}',
            # 反思（工具失败触发）
            '{"what_failed": "nonexistent_tool", "why": "未注册", "next_hypothesis": "换工具", "avoid": ["nonexistent_tool"]}',
            '{"tool": null, "final": true, "answer": "handled"}',
            '{"confidence": 0.1}',
        ])
        result = run_reasoning("reflexion", "任务", llm=llm)
        assert result.answer == "handled"
        # 工具错误被记录为观察，且触发了反思（额外 LLM 调用）
        assert result.total_tool_calls == 1
        assert len(llm.calls) == 4  # 决策1 + 反思 + 决策2 + self-assess
