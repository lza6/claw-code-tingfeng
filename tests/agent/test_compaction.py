"""上下文检查点压缩测试（对齐 Codex 的 compact 语义）"""

from __future__ import annotations

from src.agent.compaction import (
    COMPACTION_PROMPT,
    MAX_SUMMARY_TOKENS,
    SUMMARY_PREFIX,
    build_checkpoint,
    extract_facts,
    render_facts,
    should_auto_compact,
)
from src.reasoning.context_engineering import HistoryProcessor


class TestTrigger:
    def test_threshold_semantics(self):
        assert should_auto_compact(100, 100) is True   # ≥ 阈值即触发（对齐 Codex）
        assert should_auto_compact(99, 100) is False
        assert should_auto_compact(0, 0) is False       # 0 = 关闭


class TestPromptAlignedWithCodex:
    def test_prompt_has_four_handoff_sections(self):
        # Codex templates/compact/prompt.md 的四段式
        for token in ("进展", "决策", "上下文", "约束", "下一步", "关键数据"):
            assert token in COMPACTION_PROMPT, f"缺少 {token}"

    def test_summary_prefix_tells_next_model_to_not_repeat(self):
        assert "继续" in SUMMARY_PREFIX or "avoid" in SUMMARY_PREFIX.lower()
        assert "摘要" in SUMMARY_PREFIX


class TestExtractFacts:
    def _entries(self):
        return [
            {"role": "user", "content": "请实现 src/api/user.py 的登录接口，目标是支持 JWT"},
            {"role": "assistant", "content": "决定用 PyJWT，写在 pyproject.toml", "is_pinned": True},
            {"role": "tool", "content": "调用工具 read_file 读取 src/api/user.py 成功"},
            {"role": "tool", "content": "执行失败: ModuleNotFoundError: No module named 'jwt'"},
            {"role": "assistant", "content": "下一步：补 tests/api/test_user.py"},
        ]

    def test_extracts_each_bucket(self):
        facts = extract_facts(self._entries())

        assert any("登录接口" in g for g in facts["目标"])
        assert any("PyJWT" in d for d in facts["关键决策（pinned）"])
        assert any("src/api/user.py" in f for f in facts["涉及文件"])
        assert any("read_file" in t for t in facts["工具调用"])
        assert any("ModuleNotFoundError" in e for e in facts["错误/风险"])
        assert any("test_user.py" in t for t in facts["待办/下一步"])

    def test_dedupes_repeated_items(self):
        entries = [{"role": "user", "content": "请实现 a.py"}] * 5
        facts = extract_facts(entries)
        assert len(facts["目标"]) == 1

    def test_caps_section_size(self):
        entries = [
            {"role": "user", "content": f"请实现 feature_{i}.py"} for i in range(20)
        ]
        facts = extract_facts(entries, max_per_section=3)
        assert len(facts["目标"]) <= 3

    def test_handles_history_entry_objects(self):
        processor = HistoryProcessor(token_budget=10)
        processor.add("user", "请实现 src/x.py")
        facts = extract_facts(processor.entries)
        assert facts["目标"]

    def test_empty_input_is_safe(self):
        facts = extract_facts([])
        assert all(v == [] for v in facts.values())
        assert "未提取到结构化事实" in render_facts(facts)


class TestBuildCheckpoint:
    def test_deterministic_without_summarizer(self):
        entries = [
            {"role": "user", "content": "请实现 payment.py，目标支持退款"},
            {"role": "tool", "content": "错误: timeout 连接数据库"},
        ]

        cp = build_checkpoint(entries)

        assert cp.used_llm is False
        assert "payment.py" in cp.summary
        assert "timeout" in cp.summary
        assert cp.dropped_entries == 2
        assert cp.dropped_tokens > 0
        assert SUMMARY_PREFIX in cp.render()

    def test_uses_summarizer_when_provided(self):
        captured = {}

        def fake_llm(prompt, entries):
            captured["prompt"] = prompt
            return "## 摘要\n- 已完成 A\n- 下一步 B"

        cp = build_checkpoint([{"role": "user", "content": "请实现 A"}], summarizer=fake_llm)

        assert cp.used_llm is True
        assert "已完成 A" in cp.summary
        assert captured["prompt"] == COMPACTION_PROMPT

    def test_summarizer_failure_falls_back_without_data_loss(self):
        def boom(prompt, entries):
            raise RuntimeError("LLM 挂了")

        cp = build_checkpoint(
            [{"role": "user", "content": "请实现 refund.py"}], summarizer=boom
        )

        assert cp.used_llm is False
        assert "refund.py" in cp.summary  # 降级后仍保住关键事实

    def test_summary_truncated_to_limit(self):
        entries = [{"role": "user", "content": "请实现 " + "x" * 5000}]
        cp = build_checkpoint(entries, max_summary_tokens=10)

        assert len(cp.summary) <= 10 * 4 + 20  # 允许截断标记的少量余量
        assert "截断" in cp.summary


class TestHistoryProcessorIntegration:
    def test_over_budget_produces_structured_checkpoint(self):
        processor = HistoryProcessor(token_budget=200, keep_recent=2)
        processor.add("user", "请实现 src/api/user.py 的登录接口，目标是支持 JWT")
        for i in range(10):
            processor.add("tool", f"调用工具 read_file 读取 file_{i}.py 成功 " + "y" * 100)
        processor.add("assistant", "下一步：补测试")

        result = processor.process()

        system_entries = [e for e in result if e.role == "system"]
        assert system_entries, "压缩必须产出检查点条目"
        joined = "\n".join(e.content for e in system_entries)
        assert "检查点摘要" in joined
        assert "src/api/user.py" in joined          # 关键文件被保住
        assert "目标" in joined                     # 结构化分节存在

    def test_checkpoint_itself_is_pinned(self):
        processor = HistoryProcessor(token_budget=100, keep_recent=1)
        for i in range(12):
            processor.add("tool", f"tool 调用 {i} " + "z" * 100)

        result = processor.process()
        systems = [e for e in result if e.role == "system"]
        assert systems and all(e.is_pinned for e in systems), "摘要必须 pinned，否则下一轮又被压"

    def test_under_budget_is_untouched(self):
        processor = HistoryProcessor(token_budget=100000)
        processor.add("user", "请实现 a.py")
        processor.add("assistant", "好的")

        result = processor.process()

        assert len(result) == 2
        assert all(e.role != "system" for e in result)

    def test_render_includes_checkpoint(self):
        processor = HistoryProcessor(token_budget=120, keep_recent=1)
        for i in range(10):
            processor.add("tool", f"tool {i} " + "q" * 100)

        rendered = processor.render()

        assert "检查点摘要" in rendered
