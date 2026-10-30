"""后端稳定性 / 内存泄漏检测（soak test）

目的：反复创建并执行 agent 后端进程，检测
  1. 宿主进程 RSS 是否持续增长（内存泄漏）
  2. 是否残留子进程（进程树未回收 → 句柄/内存泄漏的常见根因）
  3. 打开句柄数与线程数是否单调增长

默认用**假的 codex 进程**（零成本、可重复）；要跑真实 codex 加 `--real`（会产生真实 LLM 调用费用）。

用法:
    venv/Scripts/python.exe scripts/soak_backend.py                 # 假进程 30 轮
    venv/Scripts/python.exe scripts/soak_backend.py --iters 100     # 更久
    venv/Scripts/python.exe scripts/soak_backend.py --real --iters 3
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil  # noqa: E402

from src.backends.codex import CodexBackend  # noqa: E402

FAKE_CODEX = '''
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
for e in [
    {"type": "thread.started", "thread_id": "soak"},
    {"type": "item.completed", "item": {"item_type": "agent_message", "text": "ok"}},
    {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
]:
    print(json.dumps(e, ensure_ascii=False))
'''


def snapshot() -> dict[str, float]:
    me = psutil.Process()
    with me.oneshot():
        rss_mb = me.memory_info().rss / 1024 / 1024
        try:
            handles = me.num_handles() if hasattr(me, "num_handles") else me.num_fds()
        except (AttributeError, psutil.Error):
            handles = -1
        threads = me.num_threads()
        children = len(me.children(recursive=True))
    return {"rss_mb": rss_mb, "handles": handles, "threads": threads, "children": children}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--real", action="store_true", help="用真实 codex（会产生费用）")
    ap.add_argument("--rss-growth-mb", type=float, default=60.0, help="RSS 允许增长上限")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="clawd-soak-"))
    if args.real:
        backend = CodexBackend(workdir=tmp)
        if not backend.available():
            print("FAIL: 未安装 codex")
            return 2
        if args.iters > 5:
            print("拒绝：真实模式单次会发起 LLM 调用，请把 --iters 控制在 5 以内")
            return 2
    else:
        script = tmp / "fake_codex.py"
        script.write_text(FAKE_CODEX, encoding="utf-8")
        backend = CodexBackend(binary=[sys.executable, str(script)], workdir=tmp)

    base = snapshot()
    print(f"基线: RSS={base['rss_mb']:.1f}MB handles={base['handles']} "
          f"threads={base['threads']} children={base['children']}")

    failures = 0
    started = time.perf_counter()
    for i in range(1, args.iters + 1):
        result = backend.run("soak ping", timeout=args.timeout)
        if not result.ok and not args.real:
            failures += 1
            print(f"  轮次 {i}: 执行异常 exit={result.exit_code} errors={result.errors[:2]}")
        if i % max(1, args.iters // 5) == 0:
            s = snapshot()
            print(f"  轮次 {i:>4}: RSS={s['rss_mb']:.1f}MB (+{s['rss_mb']-base['rss_mb']:.1f}) "
                  f"handles={s['handles']} (+{s['handles']-base['handles']}) "
                  f"threads={s['threads']} children={s['children']}")

    end = snapshot()
    elapsed = time.perf_counter() - started
    # 残留子进程检查（最关键的泄漏信号）
    time.sleep(1.0)
    leftover = len(psutil.Process().children(recursive=True))

    print(f"\n合计 {args.iters} 轮 / {elapsed:.1f}s")
    print(f"末态: RSS={end['rss_mb']:.1f}MB (+{end['rss_mb']-base['rss_mb']:.1f}) "
          f"handles={end['handles']} (+{end['handles']-base['handles']}) "
          f"threads={end['threads']} (+{end['threads']-base['threads']}) "
          f"残留子进程={leftover}")

    ok = True
    rss_growth = end["rss_mb"] - base["rss_mb"]
    if rss_growth > args.rss_growth_mb:
        print(f"FAIL: RSS 增长 {rss_growth:.1f}MB 超过阈值 {args.rss_growth_mb}MB（疑似内存泄漏）")
        ok = False
    if leftover > 0:
        print(f"FAIL: 有 {leftover} 个残留子进程（进程树未回收）")
        ok = False
    if base["handles"] > 0 and end["handles"] > base["handles"] * 1.5 + 20:
        print(f"FAIL: 句柄数异常增长 {base['handles']} → {end['handles']}")
        ok = False
    if end["threads"] > base["threads"] + 10:
        print(f"FAIL: 线程数异常增长 {base['threads']} → {end['threads']}")
        ok = False
    if failures:
        print(f"FAIL: {failures} 轮执行失败")
        ok = False

    print("SOAK: PASS" if ok else "SOAK: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
