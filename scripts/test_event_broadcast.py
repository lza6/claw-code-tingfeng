"""验证引擎 step 事件是否实时广播到 WS 客户端"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import websockets

from dotenv import load_dotenv
from src.server import create_server


async def main():
    load_dotenv()
    (Path.cwd() / "e2e_probe.txt").write_text("EVENT_TEST_42", encoding="utf-8")
    server = create_server(host="127.0.0.1", port=0, token="t")
    host, port = await server.start()
    events: list[dict] = []
    try:
        async with websockets.connect(f"ws://{host}:{port}") as ws:
            await ws.send(json.dumps({"type": "auth", "token": "t", "id": "auth"}))
            await asyncio.wait_for(ws.recv(), timeout=5)

            async def reader():
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("type") == "event":
                        events.append(msg)

            read_task = asyncio.create_task(reader())
            await ws.send(json.dumps({
                "type": "run",
                "goal": "请用 FileReadTool 读取 e2e_probe.txt，只回复其内容。",
                "id": "run-1",
            }))
            # 等 run 完成（response id=run-1）
            deadline = asyncio.get_event_loop().time() + 120
            done = False
            while asyncio.get_event_loop().time() < deadline:
                done = len([e for e in events if e.get("event") == "AGENT_TASK_COMPLETED"]) > 0
                if done:
                    break
                await asyncio.sleep(0.5)
            read_task.cancel()
            names = [e.get("event") for e in events]
            print(f"收到事件 {len(events)} 个:")
            for n in names[:15]:
                print("  -", n)
            print("TOOL_STARTED" if any("TOOL_EXEC_STARTED" in (n or "") for n in names) else "NO_TOOL_EVENTS")
    finally:
        await server.stop()
        (Path.cwd() / "e2e_probe.txt").unlink(missing_ok=True)


asyncio.run(main())
