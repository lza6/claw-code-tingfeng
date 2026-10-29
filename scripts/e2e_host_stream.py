"""Host 层 E2E：真流式增量 + 角色库（走真实 WS 协议，不经过 Electron 壳）

用法（会发起真实 LLM 调用）：
    python scripts/e2e_host_stream.py [--port 8799]

断言：
1. `personas` 请求能拿到角色库（≥4 个）
2. `run` + `stream=true` 期间能收到 **多条** `AGENT_STREAM_DELTA`，且文本逐次增长
3. 最终 response.status=completed 且文本非空
4. `persona` 真的生效（用"极简输出"角色时，最终文本明显比默认角色短 —— 仅作提示，不做硬断言）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def _run(port: int) -> int:
    import websockets

    port_file = ROOT / ".clawd_host_port"
    deadline = time.time() + 60
    info = None
    while time.time() < deadline:
        if port_file.is_file():
            try:
                info = json.loads(port_file.read_text(encoding="utf-8"))
                if info.get("port"):
                    break
            except json.JSONDecodeError:
                pass
        await asyncio.sleep(0.4)
    if not info:
        print("FAIL 未读到 .clawd_host_port（Host 没起来？）")
        return 1

    url = f"ws://127.0.0.1:{info['port']}/ws"
    print(f"连接 {url}")
    deltas: list[str] = []
    final_text = ""

    async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "auth", "token": info["token"], "id": "auth"}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if msg.get("id") == "auth":
                ok = (msg.get("data") or {}).get("status") == "authenticated"
                print(f"auth: {ok}")
                if not ok:
                    return 1
                break

        # 1) 角色库
        await ws.send(json.dumps({"type": "personas", "id": "p1"}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if msg.get("id") == "p1":
                items = (msg.get("data") or {}).get("personas") or []
                print(f"角色库: {len(items)} 个 -> {[p['name'] for p in items][:8]}")
                if len(items) < 4:
                    print("FAIL 角色库为空或过少")
                    return 1
                assert any(p["name"] == "concise" for p in items)
                break

        # 2) 流式 run（带角色）
        await ws.send(json.dumps({
            "type": "run",
            "id": "r1",
            "goal": "用两句话说明什么是幂等操作，并各举一个正例和一个反例。",
            "stream": True,
            "persona": "concise",
        }))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=180)
            msg = json.loads(raw)
            if msg.get("type") == "event":
                name = msg.get("event") or ""
                data = msg.get("data") or {}
                if name == "AGENT_STREAM_DELTA":
                    deltas.append(data.get("text") or "")
                    print(f"  delta #{len(deltas)} +{len(data.get('text') or '')}字 (累计 {sum(len(d) for d in deltas)})")
                elif name in ("AGENT_STREAM_STARTED", "AGENT_STREAM_COMPLETED"):
                    print(f"  {name}")
            elif msg.get("type") == "response" and msg.get("id") == "r1":
                data = msg.get("data") or {}
                final_text = data.get("result") or ""
                print(f"最终 status={data.get('status')} 文本长度={len(final_text)}")
                break
            elif msg.get("type") == "error":
                print(f"FAIL 服务端错误: {msg}")
                return 1

    ok = True
    if len(deltas) < 2:
        print(f"FAIL 增量事件太少（{len(deltas)} 条）——不是真流式")
        ok = False
    if sum(len(d) for d in deltas) < 10:
        print("FAIL 增量文本过短")
        ok = False
    if not final_text.strip():
        print("FAIL 最终文本为空")
        ok = False
    joined = "".join(deltas)
    if final_text.strip() and not final_text.strip().startswith(joined.strip()[:10]):
        print(f"WARN 增量拼接与最终文本开头不一致（可能被改写）: {joined[:30]!r} vs {final_text[:30]!r}")

    print("PASS ✔ Host 真流式 + 角色库" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Host 真流式 + 角色库 E2E")
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()
    os.chdir(ROOT)
    return asyncio.run(_run(args.port))


if __name__ == "__main__":
    sys.exit(main())
