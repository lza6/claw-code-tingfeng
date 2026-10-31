"""启动预算门禁 —— 度量并断言 CLI 启动成本，超预算以退出码 1 失败。

## 为什么需要它

"启动越来越慢"是一个没人报 bug、也没有测试会红的回归：多一个 import、
多一次模块级网络/磁盘探测，用户每次敲 `clawd` 都要多等几百毫秒，而 CI 全绿。
本脚本把启动成本变成**可执行的断言**：全部指标在预算内才退出 0。

## 度量项（全部走真实子进程，不在本进程 import 后假装）

| 指标 | 怎么测 |
|:---|:---|
| `version_time` | `python -m src --version` 的墙钟时间 |
| `entrypoint_import_time` | 子进程内 `perf_counter()` 包住 `import src.cli.entrypoint` |
| `module_count` | 同一子进程里的 `len(sys.modules)`（import 副作用膨胀的信号） |
| `doctor_time` | `python -m src doctor --json` 的墙钟时间 |

默认解释器是 `sys.executable`：脚本用哪个解释器启动，就测哪个（`--python` 可覆盖）。

## 退出码

- `0` 全部在预算内
- `1` 有指标超预算
- `2` 无法测量（子进程失败/超时/输出不可解析）——**优先于 1**

单项测量失败不会让脚本崩溃：如实记进 `violations` 的 `error` 字段，其余项照常测。

## 预算基线

见下方 `MEASURED_2026_10_31` 与 `DEFAULT_BUDGETS` 的注释：实测值 × 1.35，
时间项向上取整到 0.05s，模块数向上取整到 10。换机器或换解释器后先跑
`--update-baseline` 看建议值，不要盲改常量。

## 用法

    venv/Scripts/python.exe scripts/startup_budget.py
    venv/Scripts/python.exe scripts/startup_budget.py --json
    venv/Scripts/python.exe scripts/startup_budget.py --repeat 5 --update-baseline
    venv/Scripts/python.exe scripts/startup_budget.py --skip-doctor   # 快速冒烟
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parents[1]

METRICS = ("version_time", "entrypoint_import_time", "module_count", "doctor_time")
TIME_METRICS = ("version_time", "entrypoint_import_time", "doctor_time")

# 2026-10-31 实测（`venv/Scripts/python.exe`，Windows 10 Pro 19045，7 次取中位数）：
#   python -m src --version          0.783s
#   import src.cli.entrypoint        0.612s（761 个已加载模块）
#   python -m src doctor --json      4.100s
# 预算 = 实测 × 1.35，时间项向上取整到 0.05s，模块数向上取整到 10。
# `tests/scripts/test_startup_budget.py` 校验默认预算与这里的实测值一致，
# 避免注释里的实测值和代码里的预算悄悄分叉。
MEASURED_2026_10_31 = {
    "version_time": 0.783,
    "entrypoint_import_time": 0.612,
    "module_count": 761,
    "doctor_time": 4.100,
}

DEFAULT_BUDGETS = {
    "version_time": 1.10,
    "entrypoint_import_time": 0.85,
    "module_count": 1030,
    "doctor_time": 5.55,
}

# 子进程探针：只 import，不跑 CLI，输出 "<import 秒数> <已加载模块数>"。
_IMPORT_PROBE = (
    "import sys, time\n"
    "start = time.perf_counter()\n"
    "import src.cli.entrypoint\n"
    "print(time.perf_counter() - start, len(sys.modules))\n"
)


def suggest_budget(actual: float, factor: float = 1.35, step: float = 0.05) -> float:
    """按"实测 × 系数、向上取整到 step"给出建议预算。"""
    if actual <= 0:
        return step
    return round(math.ceil(round(actual * factor / step, 9)) * step, 2)


def suggest_module_budget(count: int, factor: float = 1.35, step: int = 10) -> int:
    """模块数的建议上限（整数，向上取整到 step）。"""
    if count <= 0:
        return step
    return int(math.ceil(count * factor / step) * step)


def _run_timed(
    python: str, args: list[str], timeout: float
) -> tuple[float | None, subprocess.CompletedProcess | None, str]:
    """跑一次子进程，返回 (墙钟秒数, CompletedProcess, 错误说明)。

    捕获 bytes 输出而不解码：`--version` 在 Windows 上可能是 GBK，
    本脚本只需要墙钟和退出码，不需要正文。
    """
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            [python, *args], cwd=str(ROOT), capture_output=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return None, None, f"超时（>{timeout:.0f}s）：{python} {' '.join(args)}"
    except OSError as exc:
        return None, None, f"无法启动子进程 {python}：{type(exc).__name__}: {exc}"
    return time.perf_counter() - start, proc, ""


def _tail(proc: subprocess.CompletedProcess | None, limit: int = 300) -> str:
    """取子进程 stderr/stdout 尾部，用于错误说明。"""
    if proc is None:
        return ""
    blob = (proc.stderr or b"") + (proc.stdout or b"")
    return blob.decode("utf-8", "replace")[-limit:].strip()


def measure_version(python: str, repeat: int, timeout: float) -> tuple[float | None, str]:
    """`python -m src --version` 的墙钟中位数。"""
    samples: list[float] = []
    for _ in range(repeat):
        elapsed, proc, err = _run_timed(python, ["-m", "src", "--version"], timeout)
        if err:
            return None, err
        if proc is None or proc.returncode != 0:
            code = proc.returncode if proc is not None else "?"
            return None, f"`-m src --version` 退出码 {code}：{_tail(proc)}"
        assert elapsed is not None
        samples.append(elapsed)
    return statistics.median(samples), ""


def measure_entrypoint(
    python: str, repeat: int, timeout: float
) -> tuple[float | None, int | None, str]:
    """`import src.cli.entrypoint` 的耗时与已加载模块数（各自取中位数）。"""
    times: list[float] = []
    counts: list[int] = []
    for _ in range(repeat):
        elapsed, proc, err = _run_timed(python, ["-c", _IMPORT_PROBE], timeout)
        if err:
            return None, None, err
        if proc is None or proc.returncode != 0:
            code = proc.returncode if proc is not None else "?"
            return None, None, f"import 探针退出码 {code}：{_tail(proc)}"
        parts = proc.stdout.decode("utf-8", "replace").split()
        if len(parts) != 2:
            return None, None, f"import 探针输出无法解析：{parts!r}"
        try:
            times.append(float(parts[0]))
            counts.append(int(parts[1]))
        except ValueError as exc:
            return None, None, f"import 探针输出无法解析：{parts!r}（{exc}）"
    return statistics.median(times), int(statistics.median(counts)), ""


def measure_doctor(python: str, repeat: int, timeout: float) -> tuple[float | None, str]:
    """`python -m src doctor --json` 的墙钟中位数。

    doctor 在有 fail 项时退出 1（环境问题），这仍是一次有效的耗时测量；
    只有 0/1 之外退出码、或 stdout 不是 JSON 对象的，才算测量失败。
    """
    samples: list[float] = []
    for _ in range(repeat):
        elapsed, proc, err = _run_timed(python, ["-m", "src", "doctor", "--json"], timeout)
        if err:
            return None, err
        if proc is None or proc.returncode not in (0, 1):
            code = proc.returncode if proc is not None else "?"
            return None, f"`-m src doctor --json` 退出码 {code}：{_tail(proc)}"
        try:
            payload = json.loads(proc.stdout.decode("utf-8", "replace"))
        except ValueError as exc:
            return None, f"`doctor --json` 输出不是 JSON：{exc}"
        if not isinstance(payload, dict):
            return None, "`doctor --json` 输出不是 JSON 对象"
        assert elapsed is not None
        samples.append(elapsed)
    return statistics.median(samples), ""


def collect(
    args: argparse.Namespace, python: str
) -> tuple[dict[str, float | int | None], dict[str, str]]:
    """跑全部测量项，返回 (值, 错误)。单项失败只记错误，不影响其它项。"""
    values: dict[str, float | int | None] = {metric: None for metric in METRICS}
    errors: dict[str, str] = {}

    if not args.skip_version:
        values["version_time"], err = measure_version(python, args.repeat, args.timeout)
        if err:
            errors["version_time"] = err

    import_time, module_count, err = measure_entrypoint(python, args.repeat, args.timeout)
    values["entrypoint_import_time"] = import_time
    values["module_count"] = module_count
    if err:
        errors["entrypoint_import_time"] = err
        errors["module_count"] = err

    if not args.skip_doctor:
        values["doctor_time"], err = measure_doctor(python, args.repeat, args.timeout)
        if err:
            errors["doctor_time"] = err

    return values, errors


def build_violations(
    values: dict[str, float | int | None],
    errors: dict[str, str],
    budgets: dict[str, float | int],
) -> list[dict[str, object]]:
    """把超预算项与测量失败项统一成 violations 列表。"""
    out: list[dict[str, object]] = []
    for metric in METRICS:
        budget = budgets[metric]
        if metric in errors:
            out.append(
                {"metric": metric, "actual": None, "budget": budget, "error": errors[metric]}
            )
            continue
        actual = values.get(metric)
        if actual is None:
            continue  # 该项被 --skip-* 跳过
        if actual > budget:
            shown = round(actual, 3) if isinstance(actual, float) else actual
            out.append({"metric": metric, "actual": shown, "budget": budget, "error": None})
    return out


def _fmt(metric: str, value: float | int) -> str:
    if metric == "module_count":
        return str(int(value))
    return f"{value:.3f}s"


def _render(report: dict[str, object], args: argparse.Namespace, stream: TextIO) -> None:
    """人类可读输出（仅非 --json 模式写 stdout）。"""
    print(f"启动预算检查（repeat={args.repeat}, python={args.python}）", file=stream)
    violations = report["violations"]
    assert isinstance(violations, list)
    errors = {v["metric"]: v["error"] for v in violations if v["error"]}
    budgets = report["budgets"]
    assert isinstance(budgets, dict)
    for metric in METRICS:
        budget = budgets[metric]
        actual = report[metric]
        if metric in errors:
            print(f"  {metric:<24} ERROR  {errors[metric]}", file=stream)
        elif actual is None:
            print(f"  {metric:<24} skipped", file=stream)
        else:
            assert isinstance(actual, (int, float)) and isinstance(budget, (int, float))
            status = "OK" if actual <= budget else "OVER"
            print(
                f"  {metric:<24} {_fmt(metric, actual):>10} / {_fmt(metric, budget):>10}  {status}",
                file=stream,
            )
    print(f"结果: code={report['code']}（0=通过 1=超预算 2=无法测量）", file=stream)


def print_suggestions(values: dict[str, float | int | None], stream: TextIO) -> None:
    """`--update-baseline`：按实测值给出建议预算，只打印，不写文件。"""
    print("建议预算（实测 × 1.35，向上取整）：", file=stream)
    for metric in TIME_METRICS:
        actual = values.get(metric)
        if isinstance(actual, (int, float)) and actual > 0:
            print(f"  {metric}: {suggest_budget(float(actual)):.2f}", file=stream)
    count = values.get("module_count")
    if isinstance(count, int) and count > 0:
        print(f"  module_count: {suggest_module_budget(count)}", file=stream)


def ensure_utf8_streams() -> None:
    """Windows 控制台默认 cp936，中文文案会乱码；显式改成 UTF-8。

    只影响本进程的 stdout/stderr。被替换成非 TextIOWrapper（如测试里的
    StringIO）时没有 `reconfigure`，跳过即可——那种场景本来就是内存流。
    """
    for stream in (sys.stdout, sys.stderr):
        if str(getattr(stream, "encoding", "")).lower().replace("-", "") == "utf8":
            continue  # pytest 捕获流/已配置好的终端，不必动
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError) as exc:
                print(f"警告：无法将输出流切换为 UTF-8：{exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="度量并断言 Clawd Code 的启动成本（超预算退出 1）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="stdout 只输出 JSON")
    parser.add_argument("--repeat", type=int, default=3, help="每项测量次数，取中位数")
    parser.add_argument("--timeout", type=float, default=180.0, help="单项子进程超时（秒）")
    parser.add_argument("--python", default=sys.executable, help="用于测量的解释器")
    parser.add_argument("--skip-version", action="store_true", help="跳过 `-m src --version`")
    parser.add_argument(
        "--skip-doctor", action="store_true", help="跳过 `-m src doctor --json`（最慢的一项）"
    )
    parser.add_argument(
        "--update-baseline", action="store_true", help="打印建议新预算（不写文件）"
    )
    parser.add_argument("--version-budget", type=float, default=None, help="覆盖 version_time 预算")
    parser.add_argument(
        "--import-budget", type=float, default=None, help="覆盖 entrypoint_import_time 预算"
    )
    parser.add_argument("--modules-budget", type=int, default=None, help="覆盖 module_count 预算")
    parser.add_argument("--doctor-budget", type=float, default=None, help="覆盖 doctor_time 预算")
    return parser


def resolve_budgets(args: argparse.Namespace) -> dict[str, float | int]:
    """默认预算 + 环境系数 + 命令行覆盖（优先级：命令行 > 环境 > 默认）

    环境系数 `CLAWD_STARTUP_BUDGET_FACTOR` 的存在理由：默认预算是**本机 Windows**
    实测值，而 CI 跑在共享 Ubuntu runner 上——CPU 更慢、磁盘更抖、pip 缓存未必热。
    用同一个绝对值会在 CI 上产生与真实回归无关的假红，而假红会让人把这条门禁
    静音掉（本仓库已有"CI 常红被无视"的历史）。所以 CI 显式放大系数，
    本机默认 1.0 保持严格。模块数是**结构量**，不随机器波动，故不乘系数。
    """
    budgets: dict[str, float | int] = dict(DEFAULT_BUDGETS)
    raw_factor = os.environ.get("CLAWD_STARTUP_BUDGET_FACTOR", "").strip()
    if raw_factor:
        try:
            factor = float(raw_factor)
        except ValueError:
            raise SystemExit(
                f"CLAWD_STARTUP_BUDGET_FACTOR 不是数字: {raw_factor!r}（应如 1.8）"
            )
        if factor <= 0:
            raise SystemExit(f"CLAWD_STARTUP_BUDGET_FACTOR 必须 > 0，实际 {factor}")
        for metric in TIME_METRICS:
            budgets[metric] = round(float(budgets[metric]) * factor, 2)
    if args.version_budget is not None:
        budgets["version_time"] = args.version_budget
    if args.import_budget is not None:
        budgets["entrypoint_import_time"] = args.import_budget
    if args.modules_budget is not None:
        budgets["module_count"] = args.modules_budget
    if args.doctor_budget is not None:
        budgets["doctor_time"] = args.doctor_budget
    return budgets


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat 必须 >= 1")
    ensure_utf8_streams()

    budgets = resolve_budgets(args)
    values, errors = collect(args, args.python)
    violations = build_violations(values, errors, budgets)

    # 无法测量优先于超预算：连数字都没有时不能报"通过"，也不能报"超预算"。
    if errors:
        code = 2
    elif violations:
        code = 1
    else:
        code = 0

    report: dict[str, object] = {
        "ok": code == 0,
        "code": code,
        "version_time": values["version_time"],
        "entrypoint_import_time": values["entrypoint_import_time"],
        "module_count": values["module_count"],
        "doctor_time": values["doctor_time"],
        "budgets": budgets,
        "violations": violations,
    }

    if args.json:
        # ensure_ascii=True：无论 CI 用什么编码读 stdout，都能 json.loads
        print(json.dumps(report, ensure_ascii=True))
    else:
        _render(report, args, sys.stdout)

    if args.update_baseline:
        print_suggestions(values, sys.stderr)

    return code


if __name__ == "__main__":
    raise SystemExit(main())
