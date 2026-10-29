"""文档数字漂移检查 —— README 里的实测数字必须与现跑结果一致

为什么需要：审计 P2-4 就是"文档写 3254 passed / 47% 覆盖率 / 可达 478 / 静默 172，
实测却是另一组数"。这类漂移会反复发生（每次改测试/删代码都会变），
人肉同步不可靠，所以做成可执行的门禁：

    venv/Scripts/python.exe scripts/check_doc_drift.py
    # 0 = 一致；1 = 有漂移（会打印"文档 X / 实际 Y"）

只检查**便宜且稳定**的三项：用例收集数、静默吞异常数、生产可达模块数。
（覆盖率要跑全量，太慢，不放进这个门禁；README 里已标注"以现跑为准"。）
"""
from __future__ import annotations

import re
import subprocess
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PY = str(ROOT / "venv" / "Scripts" / "python.exe")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    # 子进程按 UTF-8 输出（否则 Windows 默认 GBK，中文提示解析不到）
    import os

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600, env=env)


def actual_collect() -> int | None:
    proc = _run([sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"])
    m = re.search(r"(\d+)\s+tests collected", (proc.stdout or "") + (proc.stderr or ""))
    return int(m.group(1)) if m else None


def actual_silent() -> int | None:
    proc = _run([PY, "scripts/check_silent_except.py", "--fail-over", "162"])
    m = re.search(r"：\s*(\d+)|:\s*(\d+)\s*$", (proc.stdout or "").strip().splitlines()[0] if proc.stdout else "")
    if m:
        return int(m.group(1) or m.group(2))
    m2 = re.search(r"(\d+)", proc.stdout or "")
    return int(m2.group(1)) if m2 else None


def actual_reachable() -> int | None:
    proc = _run([PY, "scripts/reachability.py", "--min-reachable", "443"])
    m = re.search(r"从生产入口可达[^:：]*[:：]\s*(\d+)", (proc.stdout or "") + (proc.stderr or ""))
    return int(m.group(1)) if m else None


def readme_numbers() -> dict[str, int]:
    text = README.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    patterns = {
        "collect": r"\| 用例收集 \| \*\*(\d+)\s*/",
        "silent": r"\| 静默吞异常 \| \*\*(\d+)\*\*",
        "reachable": r"\| 生产可达模块 \| \*\*(\d+)\*\*",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            out[key] = int(m.group(1))
    return out


def main() -> int:
    documented = readme_numbers()
    checks = {
        "collect": (documented.get("collect"), actual_collect, "用例收集"),
        "silent": (documented.get("silent"), actual_silent, "静默吞异常"),
        "reachable": (documented.get("reachable"), actual_reachable, "生产可达模块"),
    }
    drift = 0
    print("=" * 66)
    print("README 数字 vs 实际")
    print("=" * 66)
    for key, (doc, fn, label) in checks.items():
        real = fn()
        mark = "OK  " if (doc is not None and real is not None and doc == real) else "DRIFT"
        if mark == "DRIFT":
            drift += 1
        print(f"[{mark}] {label}: 文档={doc} 实际={real}")
    print("-" * 66)
    if drift:
        print(f"{drift} 项漂移 —— 请把 README 改成实际值（或说明为什么保留旧值）")
    else:
        print("全部一致")
    print("=" * 66)
    return 0 if drift == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
