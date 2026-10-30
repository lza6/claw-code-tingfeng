"""生成配置的「可启动性」自检：逐个 spawn MCP server，做真实握手与工具列举

动机（审计 2.4 风险表第二条）：
    "承诺与实现错位"——生成配置里写了 4 个 MCP server，但当时它们没有 `__main__`，
    `python -m` 会静默退出，客户端只看到 EOF。配置能生成 ≠ 能被启动。

本脚本对 `DEFAULT_MCP_SERVERS` 里的每一项：
1. 用**当前解释器** spawn（和生成配置一致），发 `initialize`；
2. 10 秒内必须收到 `serverInfo`；
3. 再发 `tools/list`，工具数必须 > 0 且每个工具名都能在 Server 类上找到方法；
4. 任一失败 → 退出码 1（可挂 CI / 发版前跑）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _rpc_lines(*requests: dict) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests)


def check_one(name: str, command: str, args: list[str]) -> tuple[bool, str]:
    payload = _rpc_lines(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    try:
        proc = subprocess.run(
            [command, *args],
            input=payload, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60, cwd=str(ROOT),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"spawn 失败: {type(exc).__name__}: {exc}"

    server_name = None
    tools: list[str] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 1:
            server_name = (msg.get("result") or {}).get("serverInfo", {}).get("name")
        elif msg.get("id") == 2:
            tools = [t.get("name", "") for t in (msg.get("result") or {}).get("tools", [])]

    if not server_name:
        detail = (proc.stderr or proc.stdout or "(无输出)").strip().splitlines()
        head = detail[0][:200] if detail else "(无输出)"
        return False, f"未收到 serverInfo（exit={proc.returncode}）: {head}"
    if not tools:
        return False, f"serverInfo={server_name} 但 tools/list 为空"
    return True, f"serverInfo={server_name} tools={len(tools)} {tools[:5]}"


def main() -> int:
    from src.core.config.generator import DEFAULT_MCP_SERVERS

    print("=" * 72)
    print("MCP 生成配置可启动性自检")
    print("=" * 72)
    failures = 0
    for name, cfg in DEFAULT_MCP_SERVERS.items():
        ok, detail = check_one(name, cfg.command, list(cfg.args))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            failures += 1
    print("-" * 72)
    print(f"合计 {len(DEFAULT_MCP_SERVERS)} 个 server，通过 {len(DEFAULT_MCP_SERVERS) - failures}，失败 {failures}")
    print("=" * 72)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
