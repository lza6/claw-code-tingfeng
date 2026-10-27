"""reason CLI handler 测试（mock litellm，不调真实 API）"""
import pytest

from src.cli_handlers import reason_handler
from src.reasoning import ReasoningResult


class _FakeResponse:
    class _Choice:
        class _Message:
            content = " fake llm output "

    choices = [_Choice()]


@pytest.fixture
def mock_litellm(monkeypatch):
    calls = []

    class _FakeLiteLLM:
        def completion(self, messages=None, **kwargs):
            calls.append(messages)
            return _FakeResponse()

    monkeypatch.setattr(
        reason_handler, "build_llm_adapter", lambda: (lambda s, u: "决策输出")
    )
    return calls


class TestCmdReason:
    def test_unknown_pattern_rejected(self, capsys):
        # argparse choices 直接退出
        with pytest.raises(SystemExit):
            reason_handler.cmd_reason(["nope", "task"])

    def test_json_output(self, mock_litellm, capsys, monkeypatch):
        # 直接 mock run_reasoning 验证输出路径
        monkeypatch.setattr(
            "src.reasoning.run_reasoning",
            lambda **kw: ReasoningResult(answer="结论X", pattern=kw["pattern"]),
        )
        code = reason_handler.cmd_reason(["reflexion", "任务", "--json"])
        assert code == 0
        out = capsys.readouterr().out
        assert '"answer": "结论X"' in out

    def test_human_output(self, mock_litellm, capsys, monkeypatch):
        monkeypatch.setattr(
            "src.reasoning.run_reasoning",
            lambda **kw: ReasoningResult(
                answer="结论Y", pattern="reflexion", iterations=2, confidence=0.8
            ),
        )
        code = reason_handler.cmd_reason(["reflexion", "任务"])
        assert code == 0
        out = capsys.readouterr().out
        assert "结论Y" in out
        assert "置信度: 0.80" in out

    def test_lats_kwargs_passed(self, mock_litellm, capsys, monkeypatch):
        captured = {}

        def fake_run(**kw):
            captured.update(kw)
            return ReasoningResult(answer="ok")

        monkeypatch.setattr("src.reasoning.run_reasoning", fake_run)
        reason_handler.cmd_reason(["lats", "任务", "--branching", "5", "--depth", "3"])
        assert captured["branching"] == 5
        assert captured["depth"] == 3

    def test_debate_conclusion_passed(self, mock_litellm, capsys, monkeypatch):
        captured = {}

        def fake_run(**kw):
            captured.update(kw)
            return ReasoningResult(answer="ok")

        monkeypatch.setattr("src.reasoning.run_reasoning", fake_run)
        reason_handler.cmd_reason(["debate", "任务", "--conclusion", "待审查结论"])
        assert captured["conclusion"] == "待审查结论"
        assert captured["rounds"] == 2  # 默认

    def test_conclusion_not_passed_to_non_debate(self, mock_litellm, capsys, monkeypatch):
        """回归：conclusion 只传 debate，其他模式不得收到该参数（曾导致 TypeError）"""
        captured = {}

        def fake_run(**kw):
            captured.update(kw)
            return ReasoningResult(answer="ok")

        monkeypatch.setattr("src.reasoning.run_reasoning", fake_run)
        reason_handler.cmd_reason(["reflexion", "任务", "--conclusion", "x"])
        assert "conclusion" not in captured

    def test_litellm_adapter_shape(self, monkeypatch):
        """build_llm_adapter 返回的函数走 litellm.completion 并取 content"""
        calls = []

        class _Resp:
            class _C:
                class _M:
                    content = "适配输出"

                message = _M()

            choices = [_C()]

        fake = type("L", (), {"completion": lambda self, messages, **kw: calls.append(messages) or _Resp()})()
        import src.llm.lazy_litellm as ll

        monkeypatch.setattr(ll, "get_litellm", lambda: fake)
        fn = reason_handler.build_llm_adapter()
        out = fn("sys", "user")
        assert out == "适配输出"
        assert calls[0][0]["role"] == "system"
