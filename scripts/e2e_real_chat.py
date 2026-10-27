"""真实对话 E2E：AgentEngine + 真实 LLM + 真实工具调用

验证链路: .env 配置 → LLMProvider(openai 兼容) → AgentEngine.run()
         → 模型发起工具调用 → 工具真实执行 → 结果回填 → 最终回复

用法:
    venv/Scripts/python.exe scripts/e2e_real_chat.py          # 快速链路验证
    venv/Scripts/python.exe scripts/e2e_real_chat.py --full   # 附加推理模式真实调用
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.settings import get_settings


def check_env() -> tuple[str, str, str]:
    """读取并校验 LLM 配置"""
    import os
    from dotenv import load_dotenv

    load_dotenv()
    provider = os.environ.get("LLM_PROVIDER", "")
    key = os.environ.get("OPENAI_API_KEY", "")
    base = os.environ.get("OPENAI_BASE_URL", "")
    model = os.environ.get("OPENAI_MODEL", "")
    if not key or not base:
        print("[SKIP] 缺少 OPENAI_API_KEY / OPENAI_BASE_URL（.env 未配置）")
        sys.exit(2)
    print(f"[env] provider={provider} model={model} base={base}")
    return key, base, model


async def test_engine_real_run() -> bool:
    """测试 1: AgentEngine 真实对话 + 工具调用"""
    from src.agent.engine import AgentEngine
    from src.llm.config import LLMConfig

    key, base, model = check_env()
    # LLMConfig 从已 load_dotenv 的环境读取
    import os

    llm_config = LLMConfig.from_env()
    if not llm_config.api_key:
        print("[FAIL] LLMConfig.from_env() 未读到 api_key")
        return False
    print(f"[llm] provider={llm_config.provider.value} model={llm_config.model}")

    workdir = Path.cwd()
    engine = AgentEngine(workdir=workdir, llm_config=llm_config)
    await engine._load_extended_tools()
    print(f"[tools] 引擎工具池: {len(engine.tools)} 个: {sorted(engine.tools)[:10]}...")

    # 任务设计：迫使模型调用真实工具（读一个我们刚创建的文件）
    # 注意: .clawd/ 是受保护目录（含明文 provider.json），探针必须放普通目录
    probe = workdir / "e2e_probe.txt"
    probe.write_text("CLAWD_E2E_SECRET_7391", encoding="utf-8")

    goal = (
        "请用 FileReadTool 读取文件 e2e_probe.txt 的内容，"
        "然后只回复文件中包含的完整字符串。不要做其他事。"
    )
    print(f"[run] goal: {goal[:60]}...")

    events: list[dict] = []

    def on_step(step, session):
        print(f"  [step] {step.step_type}: {step.action[:70]} | ok={step.success}")

    session = await engine.run(goal, on_step=on_step)
    final = session.final_result or ""
    if not final:
        # 兜底：取最后成功的 report/llm 步骤结果
        for s in reversed(session.steps):
            if s.step_type in ("report", "llm") and s.result:
                final = s.result
                break
    print(f"[final] {final[:300]}")
    ok = "CLAWD_E2E_SECRET_7391" in final
    print(f"[result] 工具链路: {'PASS' if ok else 'FAIL'}")
    return ok


async def test_reason_real() -> bool:
    """测试 2: 推理模式真实 LLM（reflexion 简单任务）"""
    from src.cli_handlers.reason_handler import build_llm_adapter
    from src.reasoning import ReasoningConfig, run_reasoning

    llm = build_llm_adapter()
    # 冒烟: LLM 只需产出合法 JSON 决策
    result = run_reasoning(
        pattern="reflexion",
        task="判断 1700 是否为闰年，用纯推理回答（不需要工具），final=true",
        llm=llm,
        config=ReasoningConfig(max_iterations=3, max_tool_calls=2),
    )
    print(f"[reason] answer: {result.answer[:200]}")
    ok = "1700" in result.answer and ("不" in result.answer or "not" in result.answer.lower()
                                       or "否" in result.answer)
    print(f"[result] 推理模式: {'PASS' if ok else 'CHECK'} (answer 含判断)")
    return ok


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="附加推理模式真实调用")
    args = parser.parse_args()

    check_env()
    results = {"engine": await test_engine_real_run()}
    if args.full:
        results["reason"] = await test_reason_real()
    if args.full:
        results["reason"] = await test_reason_real()

    print("\n===== 真实对话 E2E 汇总 =====")
    all_ok = True
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
