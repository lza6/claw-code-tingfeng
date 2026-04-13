import asyncio
import json
from pathlib import Path
from src.brain.world_model import RepositoryWorldModel

async def main():
    root = Path('.').absolute()
    wm = RepositoryWorldModel(root)
    print("正在初始化 WorldModel...")
    await wm.initialize()

    stats = wm.stats()
    print(f"\n项目统计: {json.dumps(stats, indent=2)}")

    # 获取核心文件的模式检测结果
    core_files = [
        'src/agent/swarm/orchestrator.py',
        'src/brain/world_model.py',
        'src/core/patch_engine.py',
        'src/self_healing/engine.py'
    ]

    print("\n核心模块设计模式:")
    for f in core_files:
        if (root / f).exists():
            ctx = wm.get_context_for_file(f)
            print(f"- {f}: {ctx.get('patterns', [])}")
        else:
            print(f"- {f}: 文件不存在")

if __name__ == "__main__":
    asyncio.run(main())
