"""推理模式 CLI handler — 把 src/reasoning 的四个推理循环暴露为 clawd 命令

用法（通过 src/cli 或 python -m src）:
    python -m src reason reflexion "分析 0x401000 的算法"
    python -m src reason lats --branching 4 "识别混淆方案"
    python -m src reason debate --conclusion "..." "审查这个结论"

LLM 由 src/llm 的适配层注入；工具走 ToolRegistry（含 mcp_external 桥接工具）。
"""
from __future__ import annotations

import argparse
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

PATTERN_HELP = "reflexion | plan-execute | lats | debate"


def build_llm_adapter() -> Any:
    """从 clawd 现有 LLM 体系（litellm）构造推理用的 LLMFn"""

    from ..llm.config import LLMConfig
    from ..llm.lazy_litellm import get_litellm

    litellm = get_litellm()
    cfg = LLMConfig.from_env()
    # 推理模式显式指定 model（litellm 需要 openai/ 前缀走自定义 base_url）
    model = cfg.model or "openai/gpt-4o-mini"
    if not model.startswith(("openai/", "anthropic/", "gemini/")) and cfg.provider.value == "openai":
        model = f"openai/{model}"
    api_base = cfg.base_url or None
    api_key = cfg.api_key or None

    def llm_fn(system: str, user: str) -> str:
        kwargs: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        if api_base:
            kwargs["api_base"] = api_base
        if api_key:
            kwargs["api_key"] = api_key
        resp = litellm.completion(model=model, **kwargs)
        return resp.choices[0].message.content or ""

    return llm_fn


def cmd_reason(argv: list[str] | None = None) -> int:
    """clawd reason <pattern> <task> [options]"""
    parser = argparse.ArgumentParser(prog="reason", description=f"推理模式（{PATTERN_HELP}）")
    parser.add_argument("pattern", choices=["reflexion", "plan-execute", "lats", "debate"])
    parser.add_argument("task", help="任务描述")
    parser.add_argument("--conclusion", default=None, help="debate 模式的待审查结论")
    parser.add_argument("--branching", type=int, default=3, help="lats 分支数")
    parser.add_argument("--depth", type=int, default=2, help="lats 深度")
    parser.add_argument("--rounds", type=int, default=2, help="debate 轮数")
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument("--json", action="store_true", help="输出 JSON 全量结果")
    args = parser.parse_args(argv)

    from ..reasoning import ReasoningConfig, run_reasoning

    try:
        llm = build_llm_adapter()
    except Exception as e:
        print(f"[错误] LLM 适配失败: {e}")
        return 1

    kwargs: dict[str, Any] = {}
    if args.pattern == "lats":
        kwargs.update(branching=args.branching, depth=args.depth)
    if args.pattern == "debate":
        kwargs.update(rounds=args.rounds)
        # conclusion 仅 debate 模式支持（其他模式的 run(task) 不接受该参数）
        if args.conclusion:
            kwargs["conclusion"] = args.conclusion

    result = run_reasoning(
        pattern=args.pattern,
        task=args.task,
        llm=llm,
        config=ReasoningConfig(max_iterations=args.max_iterations),
        **kwargs,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"模式: {result.pattern}  迭代: {result.iterations}  工具调用: {result.total_tool_calls}")
        print(f"置信度: {result.confidence:.2f}")
        print(f"\n{result.answer}")
        if result.steps:
            print("\n--- 步骤摘要 ---")
            for s in result.steps[-5:]:
                final_mark = " [最终]" if s.is_final else ""
                print(f"  step {s.step}: {s.action[:100]}{final_mark}")
    return 0
