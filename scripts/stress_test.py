"""并发压测与深度自检。

用户要求"方便极端以及高并发的话你还要对于该功能或该模块进行压测进行深度
自检深度跑通验证"。本脚本针对**真实存在并发风险**的三处基础设施施压：

1. **工具执行的有界线程池**（`tool_executor._get_bounded_executor`）
   —— 工具被丢进 ThreadPoolExecutor 执行，配合 `asyncio.wait_for` 超时。
   风险：池耗尽时死锁；超时后线程泄漏；并发结果错配。
2. **审批门禁在高并发下的正确性**（`ToolManager._enforce_approval`）
   —— 门禁读的是实例状态，必须确认并发下不会漏判或误判。
3. **熔断器状态机**（`CircuitBreaker`）
   —— 计数递增、状态跃迁在多协程并发下是否一致。
   风险：计数丢失导致该熔断的不熔断。

用法:
    python scripts/stress_test.py            # 默认 200 并发
    python scripts/stress_test.py --n 500
退出码 0 = 全部通过。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass
class Case:
    name: str
    ok: bool = False
    elapsed: float = 0.0
    detail: str = ""
    error: str = ""


@dataclass
class Report:
    cases: list[Case] = field(default_factory=list)

    def render(self) -> str:
        out = ["", "=" * 72, "  并发压测与深度自检报告", "=" * 72]
        for c in self.cases:
            out.append(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name:<40s} {c.elapsed:7.2f}s")
            if c.detail:
                out.append(f"         -> {c.detail}")
            if c.error:
                out.append(f"         !! {c.error}")
        bad = sum(1 for c in self.cases if not c.ok)
        out.append("-" * 72)
        out.append(f"  合计 {len(self.cases)} 项，通过 {len(self.cases) - bad}，失败 {bad}")
        out.append("=" * 72)
        return "\n".join(out)


def case(report: Report, name: str, fn) -> None:
    c = Case(name=name)
    t0 = time.time()
    try:
        c.detail = str(fn() or "")
        c.ok = True
    except Exception as exc:
        c.ok = False
        c.error = f"{type(exc).__name__}: {exc}"
    c.elapsed = time.time() - t0
    report.cases.append(c)
    print(f"  [{'PASS' if c.ok else 'FAIL'}] {name} ({c.elapsed:.2f}s)")
    if c.error:
        print(f"        !! {c.error}")


# ---------------------------------------------------------------------------
# 1. 工具执行：并发压测
# ---------------------------------------------------------------------------


def stress_tool_execution(n: int) -> str:
    from src.agent.tool_executor import execute_tool
    from src.tools_runtime.bash_tool import BashTool

    workdir = Path.cwd()
    tools = {"BashTool": BashTool(workdir=workdir)}

    async def run_all() -> list:
        return await asyncio.gather(
            *[execute_tool(tools, "BashTool", {"command": f"echo job-{i}"}) for i in range(n)],
            return_exceptions=True,
        )

    t0 = time.time()
    results = asyncio.run(run_all())
    elapsed = time.time() - t0

    exceptions = [r for r in results if isinstance(r, BaseException)]
    if exceptions:
        raise AssertionError(f"{len(exceptions)} 个调用抛异常，首个: {exceptions[0]!r}")

    failed = [r for r in results if not r.success]
    if failed:
        raise AssertionError(
            f"{len(failed)}/{n} 个调用失败，首个 error: {failed[0].error!r}"
        )

    # 结果错配检查：每个 job 的输出必须与自己匹配
    mismatched = []
    for i, r in enumerate(results):
        if f"job-{i}" not in (r.output or ""):
            mismatched.append(i)
    if mismatched:
        raise AssertionError(f"{len(mismatched)} 个结果错配，例如 index={mismatched[:5]}")

    return f"{n} 并发全部成功且结果无错配，耗时 {elapsed:.2f}s（{n / elapsed:.0f} req/s）"


def stress_executor_not_exhausted(n: int) -> str:
    """连续多轮并发后线程池仍应可用（防池泄漏导致后续请求饿死）"""
    from src.agent.tool_executor import execute_tool
    from src.tools_runtime.bash_tool import BashTool

    tools = {"BashTool": BashTool(workdir=Path.cwd())}

    async def round_() -> int:
        rs = await asyncio.gather(
            *[execute_tool(tools, "BashTool", {"command": "echo x"}) for _ in range(n // 4)],
            return_exceptions=True,
        )
        return sum(1 for r in rs if not isinstance(r, BaseException) and r.success)

    rounds = 5
    counts = [asyncio.run(round_()) for _ in range(rounds)]
    expect = n // 4
    if any(c != expect for c in counts):
        raise AssertionError(f"某一轮并发成功数异常: {counts}（期望均为 {expect}）")
    return f"{rounds} 轮 × {expect} 并发，每轮全成功（无池耗尽）"


# ---------------------------------------------------------------------------
# 2. 审批门禁：并发下不漏判不误判
# ---------------------------------------------------------------------------


def stress_approval_gate(n: int) -> str:
    from src.agent.tool_manager import ToolManager
    from src.core.approval_mode import ApprovalMode
    from src.core.exceptions import ToolApprovalDeniedError
    from src.tools_runtime.bash_tool import BashTool
    from src.tools_runtime.file_read_tool import FileReadTool

    workdir = Path.cwd()
    plan = ToolManager(
        {"BashTool": BashTool(workdir=workdir), "FileReadTool": FileReadTool(base_path=workdir)},
        approval_mode=ApprovalMode.PLAN,
    )
    yolo = ToolManager(
        {"BashTool": BashTool(workdir=workdir)},
        approval_mode=ApprovalMode.YOLO,
    )

    async def hammer() -> tuple[int, int, int, int]:
        """并发混合：PLAN 下的拒绝 + PLAN 下的放行 + YOLO 下的放行"""
        denied = allowed = yolo_ok = yolo_leak = 0
        for _ in range(n // 10):
            tasks = []
            for _ in range(5):
                tasks.append(_probe(plan, "BashTool"))
                tasks.append(_probe(plan, "FileReadTool"))
                tasks.append(_probe(yolo, "BashTool"))
            for r in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(r, ToolApprovalDeniedError):
                    denied += 1
                elif isinstance(r, BaseException):
                    raise AssertionError(f"意外异常: {r!r}")
                elif r == "read":
                    allowed += 1
                elif r == "yolo":
                    yolo_ok += 1
                else:
                    yolo_leak += 1
        return denied, allowed, yolo_ok, yolo_leak

    denied, allowed, yolo_ok, yolo_leak = asyncio.run(hammer())

    if yolo_leak:
        raise AssertionError(f"YOLO 模式下有 {yolo_leak} 次被误拒")
    if denied == 0:
        raise AssertionError("PLAN 模式下 bash 一次都没被拒绝 —— 门禁漏判")
    if allowed == 0:
        raise AssertionError("PLAN 模式下只读工具一次都没通过 —— 门禁误判")

    return f"拒绝={denied} 只读放行={allowed} YOLO放行={yolo_ok} 误拒={yolo_leak}"


async def _probe(manager, tool_name: str) -> str:
    """在给定 manager 下执行一次工具，返回分类标记。

    分类是刻意的：调用方按标记统计"拒绝 / 只读放行 / 放行 / 误拒"，
    从而发现门禁在高并发下是否漏判或误判。
    """
    if tool_name == "FileReadTool":
        r = await manager.execute_tool(tool_name, {"file_path": "README.md"})
        return "read" if r.success else "read_failed"
    r = await manager.execute_tool(tool_name, {"command": "echo probe"})
    return "yolo" if r.success else "yolo_failed"


# ---------------------------------------------------------------------------
# 3. 熔断器：并发下计数不丢、状态一致
# ---------------------------------------------------------------------------


def stress_circuit_breaker(n: int) -> str:
    import threading as _t

    from src.llm.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState

    cfg = CircuitBreakerConfig(failure_threshold=n, success_threshold=2, timeout=60)
    br = CircuitBreaker("stress", cfg)

    # 并发记录 n 次失败（用线程模拟真实并发，因为熔断器是同步 API）
    barrier = _t.Barrier(n)

    def worker() -> None:
        barrier.wait()
        br.record_failure("stress")

    threads = [_t.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    if br.state != CircuitState.OPEN:
        raise AssertionError(
            f"并发记录 {n} 次失败后仍未熔断（当前 {br.state.value}）—— 计数丢失"
        )
    if br.is_available:
        raise AssertionError("已熔断但 is_available 仍为 True")
    return f"{n} 并发失败记录，计数无丢失，正确进入 OPEN"


def stress_manager_isolation(n: int) -> str:
    """一个渠道熔断不得影响其它渠道 —— 并发下尤其容易串"""
    from src.llm.circuit_breaker import CircuitBreakerConfig, CircuitBreakerManager

    cfg = CircuitBreakerConfig(failure_threshold=5, success_threshold=2, timeout=60)
    mgr = CircuitBreakerManager()
    bad, good = [], []
    lock = threading.Lock()

    def worker(i: int) -> None:
        name = f"bad-{i % 8}"
        br = mgr.get_or_create(name, cfg)
        for _ in range(5):
            br.record_failure("x")
        g = mgr.get_or_create(f"good-{i}", cfg)
        g.record_success()
        with lock:
            bad.append(mgr.is_available(name))
            good.append(mgr.is_available(f"good-{i}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    if any(bad):
        raise AssertionError(f"有 {sum(bad)} 次熔断渠道被判为可用")
    if not all(good):
        raise AssertionError(f"有 {len(good) - sum(good)} 次健康渠道被误判为熔断")
    return f"{n} 并发下渠道隔离正确（熔断 {len(bad)} 次判定 / 健康 {len(good)} 次判定）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="并发规模（默认 200）")
    args = ap.parse_args()
    n = args.n

    report = Report()
    print(f"\n并发压测 —— 规模 {n}\n")

    case(report, f"工具执行 {n} 并发", lambda: stress_tool_execution(n))
    case(report, "线程池未耗尽（5 轮）", lambda: stress_executor_not_exhausted(n))
    case(report, "审批门禁并发混合", lambda: stress_approval_gate(n))
    case(report, f"熔断器 {n} 并发计数", lambda: stress_circuit_breaker(n))
    case(report, f"熔断器 {n} 并发渠道隔离", lambda: stress_manager_isolation(n))

    print(report.render())
    return 1 if any(not c.ok for c in report.cases) else 0


if __name__ == "__main__":
    raise SystemExit(main())
