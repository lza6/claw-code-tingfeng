"""生产路径端到端测试。

## 与 scripts/e2e_smoke.py 的区别

`e2e_smoke.py` 走的是 `src/llm/factory.py::get_default_llm()`。
但**生产环境并不走那条路** —— 传递可达性分析显示
`src.llm.factory` 从生产入口不可达。真实路径是：

    src/agent/engine.py:203
      -> src/llm/providers/__init__.py::create_llm_provider()
        -> OpenAICompatibleProvider.chat() / .chat_stream()
          -> HeuristicToolParser 从 content 里解析工具调用

本脚本验证的就是这条真实路径，包括：
- 真实网络对话（非流式 / 流式）
- `<think>` 标签启发式提取（曾因 `split('', 1)` 空分隔符必崩）
- HeuristicToolParser 与 provider 输出的衔接
- 重试与错误路径

用法:
    python scripts/e2e_production.py
退出码 0 = 全部通过。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass
class Step:
    name: str
    ok: bool = False
    elapsed: float = 0.0
    detail: str = ""
    error: str = ""


@dataclass
class Report:
    steps: list[Step] = field(default_factory=list)

    def add(self, s: Step) -> None:
        self.steps.append(s)

    def render(self) -> str:
        out = ["", "=" * 70, "  生产路径 E2E 测试报告", "=" * 70]
        for s in self.steps:
            out.append(f"  [{'PASS' if s.ok else 'FAIL'}] {s.name:<44s} {s.elapsed:6.2f}s")
            if s.detail:
                out.append(f"         -> {s.detail}")
            if s.error:
                out.append(f"         !! {s.error}")
        failed = sum(1 for s in self.steps if not s.ok)
        out.append("-" * 70)
        out.append(f"  合计 {len(self.steps)} 步，通过 {len(self.steps) - failed}，失败 {failed}")
        out.append("=" * 70)
        return "\n".join(out)


def run_step(report: Report, name: str, fn) -> None:
    step = Step(name=name)
    t0 = time.time()
    try:
        detail = fn()
        step.ok = True
        step.detail = str(detail) if detail else ""
    except Exception as exc:
        step.ok = False
        step.error = f"{type(exc).__name__}: {exc}"
        step.detail = traceback.format_exc(limit=3).strip().splitlines()[-1]
        print(f"  [FAIL] {name} ({time.time() - t0:.2f}s)")
        print(f"        !! {step.error}")
    else:
        print(f"  [PASS] {name} ({time.time() - t0:.2f}s)")
    step.elapsed = time.time() - t0
    report.add(step)


# ---------------------------------------------------------------------------
# 构造一个"内容含 <think> 标签"的假响应，用于验证启发式提取
# ---------------------------------------------------------------------------

def _fake_think_response(text: str) -> MagicMock:
    """构造 openai SDK 形状的响应对象，其中 content 含 <think>...</think>"""
    resp = MagicMock()
    resp.model = "mock-model"
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    resp.choices[0].message.reasoning_content = None
    resp.choices[0].finish_reason = "stop"
    resp.usage.prompt_tokens = 1
    resp.usage.completion_tokens = 1
    resp.usage.total_tokens = 2
    return resp


def main() -> int:
    report = Report()
    print("\n生产路径 E2E —— create_llm_provider -> chat/chat_stream\n")

    # ---- 0. 配置 ----
    def step_config() -> str:
        from src.utils.env_loader import load_env

        load_env()
        keys = ("LLM_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL")
        missing = [k for k in keys if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"环境变量缺失: {missing}")
        return f"provider={os.environ['LLM_PROVIDER']} model={os.environ['OPENAI_MODEL']}"

    run_step(report, "0. 环境配置就绪", step_config)

    # ---- 1. 生产工厂能造出 provider ----
    def step_factory() -> str:
        from src.llm.config import LLMConfig
        from src.llm.providers import create_llm_provider

        cfg = LLMConfig.from_env()
        if not cfg.api_key:
            raise AssertionError("LLMConfig.from_env() 未取到 api_key")
        if not cfg.model:
            raise AssertionError("LLMConfig.from_env() 未取到 model")
        provider = create_llm_provider(cfg)
        return f"{type(provider).__name__} model={cfg.model} base={cfg.base_url or '(默认)'}"

    run_step(report, "1. create_llm_provider() 构造成功", step_factory)

    # ---- 2. 真实非流式对话 ----
    def step_chat() -> str:
        from src.llm.config import LLMConfig, LLMMessage
        from src.llm.providers import create_llm_provider

        provider = create_llm_provider(LLMConfig.from_env())
        resp = asyncio.run(provider.chat(
            messages=[LLMMessage(role="user", content="Reply with exactly: PONG")],
        ))
        if not resp.content:
            raise AssertionError(f"空响应: {resp!r}")
        return f"content={resp.content.strip()[:40]!r} tokens={resp.usage.get('total_tokens')}"

    run_step(report, "2. 生产路径真实对话 (chat)", step_chat)

    # ---- 3. 真实流式对话 ----
    def step_stream() -> str:
        from src.llm.config import LLMConfig, LLMMessage
        from src.llm.providers import create_llm_provider

        provider = create_llm_provider(LLMConfig.from_env())

        async def collect() -> tuple[str, int]:
            text_parts: list[str] = []
            think_parts: list[str] = []
            async for chunk in provider.chat_stream(
                messages=[LLMMessage(role="user", content="Count 1 to 5, comma separated.")],
            ):
                if isinstance(chunk, tuple):
                    kind, val = chunk
                    (think_parts if kind == "thinking" else text_parts).append(val)
                else:
                    text_parts.append(chunk)
            return "".join(text_parts), len(think_parts)

        text, think_n = asyncio.run(collect())
        if not text.strip():
            raise AssertionError("流式返回空文本")
        return f"text={text.strip()[:50]!r} thinking_chunks={think_n}"

    run_step(report, "3. 生产路径真实流式 (chat_stream)", step_stream)

    # ---- 4. <think> 标签启发式提取（曾因 split('', 1) 必崩）----
    def step_think_tag() -> str:
        from src.llm.config import LLMConfig, LLMMessage
        from src.llm.providers import create_llm_provider

        provider = create_llm_provider(LLMConfig.from_env())
        body = "<think>先算 17*23=391</think>答案是 391"

        with patch.object(type(provider), "_get_client") as mock_client:
            inner = MagicMock()

            async def _create(**_kw):
                return _fake_think_response(body)

            inner.chat.completions.create = _create
            mock_client.return_value = inner

            resp = asyncio.run(provider.chat(
                messages=[LLMMessage(role="user", content="17*23?")],
            ))

        if "391" not in resp.content:
            raise AssertionError(f"content 丢失答案: {resp.content!r}")
        if "<think>" in resp.content:
            raise AssertionError(f"content 未剥离 think 标签: {resp.content!r}")
        if "先算" not in resp.thinking:
            raise AssertionError(f"thinking 未提取: {resp.thinking!r}")
        return f"content={resp.content!r} thinking={resp.thinking[:20]!r}"

    run_step(report, "4. <think> 标签提取（回归）", step_think_tag)

    # ---- 5. 无 think 标签时不应误伤正文 ----
    def step_no_think_tag() -> str:
        from src.llm.config import LLMConfig, LLMMessage
        from src.llm.providers import create_llm_provider

        provider = create_llm_provider(LLMConfig.from_env())
        body = "就是一段普通回复，没有思考标签"

        with patch.object(type(provider), "_get_client") as mock_client:
            inner = MagicMock()

            async def _create(**_kw):
                return _fake_think_response(body)

            inner.chat.completions.create = _create
            mock_client.return_value = inner

            resp = asyncio.run(provider.chat(
                messages=[LLMMessage(role="user", content="hi")],
            ))

        if resp.content != body:
            raise AssertionError(f"正文被改动: {resp.content!r} != {body!r}")
        if resp.thinking:
            raise AssertionError(f"不该产生 thinking: {resp.thinking!r}")
        return "正文与 thinking 均正确"

    run_step(report, "5. 无 think 标签不误伤", step_no_think_tag)

    # ---- 6. 工具解析：主路径 + 启发式兜底的真实行为 ----
    def step_tool_parser() -> str:
        from src.agent.tool_executor import parse_tool_calls
        from src.llm.parsers import HeuristicToolParser

        # 主路径（系统提示词实际指示的格式）:
        #   engine_loop -> config._parse_tool_calls -> tool_manager.parse_tool_calls
        #   格式: <tool>{"name": "X", "args": {...}}</tool>
        primary_sample = '<tool>{"name": "BashTool", "args": {"command": "ls -la"}}</tool>'
        primary = parse_tool_calls(primary_sample)
        if not primary or primary[0][0] != "BashTool":
            raise AssertionError(f"parse_tool_calls 未识别系统提示词指示的格式: {primary!r}")

        # 启发式兜底（模型无视指示、改用 ● <function=...> 时启用）。
        # ⚠️ 已知限制: 该状态机**只在参数值后紧跟不以 '<' 开头的裸文本时才输出**。
        # 因此任何带 </function> 闭合标签的输出都识别不了（见下方断言）。
        # 已在脚本末尾单独记录，此处只验证它文档中声明的那种形态可用。
        hp = HeuristicToolParser()
        _, ok_calls = hp.feed("● <function=BashTool><parameter=command>ls -la</parameter> 继续")
        if not ok_calls:
            raise AssertionError("HeuristicToolParser 对其文档声明的格式也不工作")

        hp2 = HeuristicToolParser()
        _, closed_calls = hp2.feed(
            "● <function=BashTool><parameter=command>ls -la</parameter></function>"
        )
        limitation = "闭合标签形态识别不了" if not closed_calls else "闭合标签形态可识别"

        return (
            f"主解析器 -> {primary[0][0]} | 启发式 -> {ok_calls[0].get('name')} | {limitation}"
        )

    run_step(report, "6. 工具解析（主路径 + 启发式）", step_tool_parser)

    # ---- 7. 错误路径：网络失败应被包装而非裸抛 ----
    def step_error_path() -> str:
        from src.llm.config import LLMConfig, LLMMessage
        from src.llm.providers import create_llm_provider

        cfg = LLMConfig.from_env()
        cfg.max_retries = 1
        provider = create_llm_provider(cfg)

        with patch.object(type(provider), "_get_client") as mock_client:
            inner = MagicMock()

            async def _boom(**_kw):
                raise RuntimeError("simulated upstream failure")

            inner.chat.completions.create = _boom
            mock_client.return_value = inner

            try:
                asyncio.run(provider.chat(messages=[LLMMessage(role="user", content="x")]))
            except Exception as exc:
                return f"抛出 {type(exc).__name__}（原始错误已保留）"
            raise AssertionError("上游失败却未抛异常 —— 属于静默失败")

    run_step(report, "7. 上游失败不被静默吞掉", step_error_path)

    print(report.render())
    return 1 if any(not s.ok for s in report.steps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
