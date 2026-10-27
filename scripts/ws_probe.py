import asyncio
import json
import sys

import websockets


async def main():
    info = json.loads(open("desktop/host/.clawd_host_port", encoding="utf-8").read())
    async with websockets.connect(f"ws://127.0.0.1:{info['port']}") as ws:
        await ws.send(json.dumps({"type": "auth", "token": info["token"], "id": "auth"}))
        r = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print("WS AUTH:", r.get("data", {}).get("status"))
        await ws.send(json.dumps({"type": "ping", "id": "p1"}))
        r2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print("WS PING:", r2.get("type"))


asyncio.run(main())
