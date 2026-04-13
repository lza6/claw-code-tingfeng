import sys
import os
from pathlib import Path

# 添加当前目录到路径
sys.path.append(os.getcwd())

from src.agent.engine import AgentEngine
from src.llm import LLMConfig, LLMProviderType

def test_engine_init():
    config = LLMConfig(provider=LLMProviderType.OPENAI, model="gpt-4o")
    engine = AgentEngine(llm_config=config)
    print("Engine initialized successfully.")
    print(f"Session Manager workdir: {engine.session_manager.workdir}")
    print(f"Edit format: {engine.edit_format}")

    # 验证 checkpoint 代理
    cp_path = engine.save_checkpoint(goal="test goal")
    print(f"Checkpoint saved to: {cp_path}")

    if cp_path.exists():
        os.remove(cp_path)
        print("Test checkpoint cleaned up.")

if __name__ == "__main__":
    try:
        test_engine_init()
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
