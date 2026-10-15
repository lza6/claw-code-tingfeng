"""真实 E2E 冒烟测试 — 使用项目自身 LLM 栈打真实端点。

运行:
    python scripts/e2e_smoke.py

退出码:
    0 = 全部通过
    1 = 存在失败

设计原则（对应 计划书/下一步改进指南.md §6.1）:
    - 使用真实网络请求，不 mock
    - 每步独立捕获异常，失败不中断后续步骤
    - 输出结构化结果，便于 CI 判定
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from dataclasses import dataclass, field

# 允许从仓库根运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Step:
    """单个 E2E 步骤的结果"""
    name: str
    ok: bool = False
    elapsed: float = 0.0
    detail: str = ""
    error: str = ""


@dataclass
class Report:
    """E2E 报告"""
    steps: list[Step] = field(default_factory=list)

    def add(self, step: Step) -> None:
        self.steps.append(step)

    @property
    def failed(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]

    def render(self) -> str:
        lines = ["", "=" * 68, "  真实 E2E 冒烟测试报告", "=" * 68]
        for s in self.steps:
            mark = "PASS" if s.ok else "FAIL"
            lines.append(f"  [{mark}] {s.name:<42s} {s.elapsed:6.2f}s")
            if s.detail:
                lines.append(f"         -> {s.detail}")
            if s.error:
                lines.append(f"         !! {s.error}")
        lines.append("-" * 68)
        lines.append(f"  合计 {len(self.steps)} 步，通过 {len(self.steps) - len(self.failed)}，失败 {len(self.failed)}")
        lines.append("=" * 68)
        return "\n".join(lines)


def run_step(report: Report, name: str, fn) -> Step:
    """执行单个步骤并记录结果（异常不外抛，保证后续步骤继续）"""
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
    step.elapsed = time.time() - t0
    report.add(step)
    print(f"  [{'PASS' if step.ok else 'FAIL'}] {name} ({step.elapsed:.2f}s)")
    if step.error:
        print(f"        !! {step.error}")
    return step


def main() -> int:
    report = Report()

    print("\n真实 E2E 冒烟测试 — 目标端点由 .env 提供\n")

    # ---- 步骤 0：环境配置就绪 ----
    def step_env() -> str:
        from src.utils.env_loader import load_env
        load_env()
        base = os.environ.get("OPENAI_BASE_URL", "")
        model = os.environ.get("OPENAI_MODEL", "")
        key = os.environ.get("OPENAI_API_KEY", "")
        if not base or not model or not key:
            raise RuntimeError(f"配置缺失 base={bool(base)} model={bool(model)} key={bool(key)}")
        return f"base={base} model={model} key=***{key[-6:]}"

    run_step(report, "0. 读取 .env 配置", step_env)

    # ---- 步骤 1：应用可导入 ----
    def step_import() -> str:
        import src.main  # noqa: F401 - 此处导入本身就是被测行为，用于验证应用可启动
        from src import __version__
        return f"src.main 可导入，版本 {__version__}"

    run_step(report, "1. 应用模块可导入", step_import)

    # ---- 步骤 2：端到端最小对话（项目自身 LLM 栈） ----
    def step_chat() -> str:
        from src.llm.factory import get_default_llm

        llm = get_default_llm()
        resp = llm.invoke(prompt=[{"role": "user", "content": "Reply with exactly: PONG"}])
        msg = resp.message
        content = msg.content if msg else None
        if not content:
            raise AssertionError(f"模型返回空内容: {resp!r}")
        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", "?") if usage else "?"
        ct = getattr(usage, "completion_tokens", "?") if usage else "?"
        return f"content={content.strip()[:40]!r} tokens(prompt={pt}, completion={ct})"

    run_step(report, "2. 项目 LLM 栈真实对话", step_chat)

    # ---- 步骤 3：工具调用能力（Agent 环路硬依赖） ----
    def step_tools() -> str:
        from src.llm.factory import get_default_llm
        from src.llm.interfaces import ToolChoiceOptions

        llm = get_default_llm()
        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }]
        resp = llm.invoke(
            prompt=[{"role": "user", "content": "What is the weather in Berlin? Use the tool."}],
            tools=tools,
            tool_choice=ToolChoiceOptions.AUTO,
        )
        msg = resp.message
        if not msg or not msg.tool_calls:
            raise AssertionError(f"模型未返回 tool_calls: content={msg.content if msg else None!r}")
        tc = msg.tool_calls[0]
        return f"tool={tc.name} args={tc.arguments}"

    run_step(report, "3. 工具调用（function calling）", step_tools)

    # ---- 步骤 4：推理内容字段被正确解析（step-5-preview 为推理模型） ----
    def step_reasoning() -> str:
        from src.llm.factory import get_default_llm

        llm = get_default_llm()
        resp = llm.invoke(
            prompt=[{"role": "user", "content": "What is 17 * 23? Think then answer with just the number."}],
            max_tokens=1024,
        )
        msg = resp.message
        content = (msg.content or "").strip() if msg else ""
        reasoning = getattr(msg, "reasoning_content", None) if msg else None
        if not content:
            raise AssertionError("内容为空——推理模型可能把 token 全用在 reasoning 上")
        return f"answer={content[:20]!r} reasoning={'有' if reasoning else '无'}"

    run_step(report, "4. 推理内容解析（reasoning_content）", step_reasoning)

    print(report.render())
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
