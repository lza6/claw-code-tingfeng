"""Host WS 并发压测 — 认证+ping+并发连接，输出 QPS/P95/错误率

用法: venv/Scripts/python.exe scripts/stress_host.py [--n 200] [--auth]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import websockets

from src.server import create_server


async def one_client(port: int, token: str, do_auth: bool, rounds: int) -> tuple[int, list[float]]:
    """单客户端：连接+（认证）+N 轮 ping。返回 (成功 ping 数, 延迟列表)"""
    ok = 0
    latencies: list[float] = []
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        if do_auth:
            await ws.send(json.dumps({"type": "auth", "token": token, "id": "a"}))
            await asyncio.wait_for(ws.recv(), timeout=10)
        for _ in range(rounds):
            t0 = time.perf_counter()
            await ws.send(json.dumps({"type": "ping", "id": "p"}))
            await asyncio.wait_for(ws.recv(), timeout=10)
            latencies.append((time.perf_counter() - t0) * 1000)
            ok += 1
    return ok, latencies


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200, help="并发客户端数")
    parser.add_argument("--rounds", type=int, default=5, help="每客户端 ping 轮数")
    args = parser.parse_args()

    server = create_server(host="127.0.0.1", port=0, token="stress-token")
    host, port = await server.start()
    try:
        t_start = time.perf_counter()
        results = await asyncio.gather(
            *[one_client(port, "stress-token", True, args.rounds) for _ in range(args.n)],
            return_exceptions=True,
        )
        wall = time.perf_counter() - t_start

        errors = [r for r in results if isinstance(r, Exception)]
        ok_list = [r for r in results if not isinstance(r, Exception)]
        total_pings = sum(r[0] for r in ok_list)
        all_lat = [l for r in ok_list for l in r[1]]
        all_lat.sort()

        p50 = all_lat[len(all_lat) // 2] if all_lat else 0
        p95 = all_lat[int(len(all_lat) * 0.95)] if all_lat else 0
        p99 = all_lat[int(len(all_lat) * 0.99)] if all_lat else 0
        qps = total_pings / wall if wall > 0 else 0

        print(f"并发客户端: {args.n}  |  成功: {len(ok_list)}  |  失败: {len(errors)}")
        if errors:
            print(f"  首个错误: {type(errors[0]).__name__}: {str(errors[0])[:120]}")
        print(f"总请求: {total_pings}  |  墙钟: {wall:.2f}s  |  QPS: {qps:.0f}")
        print(f"延迟  P50: {p50:.1f}ms  P95: {p95:.1f}ms  P99: {p99:.1f}ms")
        err_rate = len(errors) / args.n * 100
        print(f"错误率: {err_rate:.1f}%")
        # 判定
        passed = len(errors) == 0 and err_rate == 0
        print("STRESS: PASS" if passed else "STRESS: FAIL")
        return 0 if passed else 1
    finally:
        await server.stop()


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
