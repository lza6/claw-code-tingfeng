#!/usr/bin/env python
"""断言构建出来的 wheel/sdist 里**必须有**什么（发布流水线的打包契约）。

为什么单独成脚本而不是在 `release.yml` 里内联 `python - <<'PY'`：
YAML 的块标量（`run: |`）要求内容整体缩进；heredoc 的正文一旦顶格写，
块标量就被提前截断，**整个 workflow 变成非法 YAML**、连触发都不会触发。
本项目已踩过 `.pre-commit-config.yaml` 内联脚本导致常红的坑，所以逻辑一律落到 .py。

历史上真实踩过的打包缺陷（本脚本存在的直接原因）：
- `prompts/agents/*.md` 没随包出去 → 装完 `clawd review` 报 `ModuleNotFoundError: prompts`
- 打包版里缺 `python3.dll` / dist-info → C 扩展 import 失败、`PackageNotFoundError`

用法：
    python scripts/verify_wheel_contents.py --dist dist --expect-version 0.90.0
    python scripts/verify_wheel_contents.py --dist dist --json
退出码：0 通过 · 1 打包契约被破坏 · 2 参数/产物不可用（如 dist 里没有 wheel）
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

#: 必须随 wheel 出去的包内路径（缺失即"装完就崩"）
#: 注意路径是**包内真实路径**：`command_result.py` 在 `src/cli/` 下，不在 `src/core/`
#: （本轮实测：凭印象写 `src/core/command_result.py` 会得到一条假失败）
REQUIRED_MEMBERS = (
    "src/__init__.py",
    "src/cli/command_result.py",
    "src/cli/entrypoint.py",
    "src/server/websocket_server.py",
)
#: `prompts/agents/*.md` 至少要有这么多（当前 34 个，留出余量；少于此说明打包规则坏了）
MIN_PROMPTS = 30


def verify(dist: Path, expect_version: str | None = None) -> dict:
    """返回结构化结果；不抛异常（调用方按 ok/exit_code 判断）"""
    result: dict = {
        "ok": False,
        "exit_code": 2,
        "dist": str(dist),
        "wheel": None,
        "sdist": None,
        "wheels": [],
        "sdists": [],
        "prompts": 0,
        "missing_members": [],
        "version_in_metadata": None,
        "problems": [],
    }
    if not dist.is_dir():
        result["problems"].append(f"dist 目录不存在: {dist}")
        return result

    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(p for p in dist.glob("*.tar.gz"))
    result["wheels"] = [p.name for p in wheels]
    result["sdists"] = [p.name for p in sdists]
    if not wheels:
        result["problems"].append("dist 里没有 wheel（构建没跑成功？）")
        return result
    wheel = wheels[0]
    result["wheel"] = wheel.name
    if sdists:
        result["sdist"] = sdists[0].name

    try:
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()
            result["prompts"] = len(
                [n for n in names if n.startswith("prompts/agents/") and n.endswith(".md")]
            )
            result["missing_members"] = [m for m in REQUIRED_MEMBERS if m not in names]

            metadata = next((n for n in names if n.endswith(".dist-info/METADATA")), None)
            if metadata is None:
                result["problems"].append("wheel 里没有 dist-info/METADATA")
            else:
                text = zf.read(metadata).decode("utf-8", errors="replace")
                for line in text.splitlines():
                    if line.startswith("Version: "):
                        result["version_in_metadata"] = line.split(":", 1)[1].strip()
                        break
    except (OSError, zipfile.BadZipFile) as exc:
        result["problems"].append(f"wheel 不可读: {type(exc).__name__}: {exc}")
        return result

    if result["prompts"] < MIN_PROMPTS:
        result["problems"].append(
            f"prompts/agents/*.md 只有 {result['prompts']} 个（要求 >= {MIN_PROMPTS}）"
            " —— 装完 `clawd review` 会 ModuleNotFoundError"
        )
    if result["missing_members"]:
        result["problems"].append(f"wheel 缺少关键模块: {result['missing_members']}")
    if expect_version:
        if result["version_in_metadata"] is None:
            result["problems"].append("METADATA 里读不到 Version")
        elif result["version_in_metadata"] != expect_version:
            result["problems"].append(
                f"METADATA 版本 {result['version_in_metadata']} != 期望 {expect_version}"
            )

    result["ok"] = not result["problems"]
    result["exit_code"] = 0 if result["ok"] else 1
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="断言 wheel/sdist 的打包契约")
    parser.add_argument("--dist", default="dist", help="构建产物目录（默认 dist）")
    parser.add_argument("--expect-version", default=None, help="期望的包版本（来自 tag）")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args(argv)

    result = verify(Path(args.dist), args.expect_version)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"wheel={result['wheel']} prompts/agents={result['prompts']} "
              f"version={result['version_in_metadata']}")
        for p in result["problems"]:
            print(f"[FAIL] {p}", file=sys.stderr)
        print("PASS" if result["ok"] else "FAILED", file=sys.stderr)
    return int(result["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
