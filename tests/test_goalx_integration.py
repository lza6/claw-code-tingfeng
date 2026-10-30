import asyncio
import logging
import os
import sys
from pathlib import Path

import pytest

# 这是**真实 LLM 端到端**测试：会走完整 Agent 循环且没有超时。
# 默认跳过，避免 `pytest tests/` 因网络/模型响应而挂起；
# 需要时显式运行：RUN_GOALX_E2E=1 pytest tests/test_goalx_integration.py
pytestmark = pytest.mark.skipif(
    os.environ.get('RUN_GOALX_E2E') != '1',
    reason='真实 LLM E2E；设置 RUN_GOALX_E2E=1 启用',
)

# 添加 src 到路径
sys.path.append(str(Path.cwd()))

from src.workflow.engine import WorkflowEngine
from src.workflow.models import WorkflowIntent


async def test_integrated_workflow():
    logging.basicConfig(level=logging.INFO)
    workdir = Path.cwd()

    print(">>> 正在初始化 WorkflowEngine...")
    try:
        engine = WorkflowEngine(
            workdir=workdir,
            intent=WorkflowIntent.EXPLORE,
            max_iterations=1
        )
        print(">>> 初始化成功。")
    except Exception as e:
        print(f">>> 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return

    print(">>> 启动整合后的 GoalX-style 工作流测试...")
    try:
        result = await engine.run("优化 src/core 中的异常处理逻辑")
        print("\n>>> 工作流执行完成！报告摘要:")
        print(result.report)
    except Exception as e:
        print(f"执行出错: {e}")

if __name__ == "__main__":
    asyncio.run(test_integrated_workflow())
