"""一条命令输出全部硬指标（JSON）。

## 为什么需要它

在它之前，`workflow_status.md` / `README.md` / `CLAUDE.md` / `test_ledger.md` /
`.agent/memory/verified-scope.md` 各自记一份数字，五份文档对同一个版本给出
五个不同结果（2026-10-23 实测：3171 / 3190 / 3165 / 2857 / 3190 并存）。
根因不是"谁不仔细"，而是**没有单一取数入口**。

本脚本把每个指标固化成一条真实子进程命令，记录 `exit_code` 与关键解析值。
**只报告实际观察到的东西**：某步失败就如实写 `status: failed`，
不做任何"按上次结果填"的兜底。

用法：
    venv/Scripts/python.exe scripts/baseline.py                     # 打印 JSON
    venv/Scripts/python.exe scripts/baseline.py --out .clawd/baseline.json
    venv/Scripts/python.exe scripts/baseline.py --with-tests        # 额外跑全量回归（很慢）
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"

# 本机 `python` 命令不存在（见 CLAUDE.md 解释器矩阵）。
VENV_PY = ROOT / "venv" / "Scripts" / "python.exe"
INTERP_TEST = [sys.executable]  # 本脚本由 py -3.10 或 venv 启动，沿用同一解释器

# 硬指标基线（**唯一来源**：scripts/hard_metrics.py；CI 与文档都从这里取语义）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hard_metrics import (  # noqa: E402 - 需先插入 scripts/ 到 sys.path
    MAX_SILENT_EXCEPT,
    MIN_COVERAGE_PERCENT,
    MIN_REACHABLE,
)

__all__ = ["MAX_SILENT_EXCEPT", "MIN_COVERAGE_PERCENT", "MIN_REACHABLE", "main"]


def _interp_runtime() -> str:
    """运行环境解释器：优先 venv，缺失则回退当前解释器。

    硬编码 `venv/Scripts/python.exe` 在 ubuntu CI 上不存在，会被 `_run` 吞成
    `status:"error" / exit_code:None`，而旧版 hard_fail 不看 collect/reachability，
    于是"什么都没测到"也能 exit=0（2026-10-23 审查实测）。
    """
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def _run(cmd: list[str], timeout: int = 900) -> dict:
    """执行命令并记录真实退出码与输出尾部。失败不抛异常，如实记录。

    强制 UTF-8 环境：本机默认 GBK，子进程输出中文会让 `text=True` 解出乱码，
    下游一旦去解析 stdout 就会得到 None（2026-10-23 审查实测：
    `reachable` 恒为 null 就是因为按中文锚点解析 GBK 输出）。
    """
    started = time.perf_counter()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return {
            "cmd": " ".join(cmd),
            "exit_code": proc.returncode,
            "status": "ok" if proc.returncode == 0 else "failed",
            "duration_s": round(time.perf_counter() - started, 2),
            "output_tail": out.strip().splitlines()[-20:],
        }
    except subprocess.TimeoutExpired:
        return {
            "cmd": " ".join(cmd),
            "exit_code": None,
            "status": "timeout",
            "duration_s": round(time.perf_counter() - started, 2),
            "output_tail": [f"超过 {timeout}s 未结束"],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "cmd": " ".join(cmd),
            "exit_code": None,
            "status": "error",
            "duration_s": round(time.perf_counter() - started, 2),
            "output_tail": [f"{type(exc).__name__}: {exc}"],
        }


def _run_to_json(cmd: list[str], json_path: Path, timeout: int = 900) -> tuple[dict, dict]:
    """跑一个支持 `--json <path>` 的门禁脚本，返回 (执行记录, 解析后的 JSON)。

    为什么走 JSON 而不是解析 stdout：stdout 里混着 642 次 import 的 loguru 日志，
    按中文锚点 + 尾部行数去抠数字，一旦环境编码或日志量变化就静默变成 None，
    而 None 又被当成"通过"（2026-10-23 审查实测 `fail/import_exit/dep_missing` 全 null）。
    """
    json_path.parent.mkdir(parents=True, exist_ok=True)
    if json_path.exists():
        json_path.unlink()
    run = _run([*cmd, "--json", str(json_path)], timeout=timeout)
    parsed: dict = {}
    if json_path.exists():
        try:
            parsed = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parsed = {"_parse_error": f"{type(exc).__name__}: {exc}"}
    else:
        parsed = {"_parse_error": "脚本未产出 JSON 文件"}
    return run, parsed


def _count_modules() -> tuple[int, int]:
    modules = list(SRC.rglob("*.py"))
    lines = 0
    for path in modules:
        try:
            lines += len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
    return len(modules), lines


def _collect_metrics() -> dict:
    res = _run([*INTERP_TEST, "-m", "pytest", "tests/", "--collect-only", "-q"])
    joined = "\n".join(res["output_tail"])
    m = re.search(r"(\d+) tests collected", joined)
    errors = len(re.findall(r"ERROR ", joined))
    return {
        "collected": int(m.group(1)) if m else None,
        "errors": errors,
        "duration_s": res["duration_s"],
        "exit_code": res["exit_code"],
        "status": res["status"],
    }


def _coverage_metrics() -> dict:
    path = ROOT / "coverage.json"
    if not path.exists():
        return {"status": "missing", "note": "coverage.json 不存在，需先跑 pytest --cov"}
    try:
        totals = json.loads(path.read_text(encoding="utf-8"))["totals"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        return {"status": "error", "note": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "ok",
        "percent_covered": round(totals.get("percent_covered", 0.0), 2),
        "covered_lines": totals.get("covered_lines"),
        "num_statements": totals.get("num_statements"),
        "file_mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    }


def _version() -> dict:
    res = _run([str(VENV_PY), "-m", "src", "--version"], timeout=180)
    version = None
    for line in reversed(res["output_tail"]):
        m = re.search(r"v(\d+\.\d+\.\d+)", line)
        if m:
            version = m.group(1)
            break
    pyproject = None
    try:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        pyproject = m.group(1) if m else None
    except OSError:
        pass
    dist_info = None
    site = ROOT / "venv" / "Lib" / "site-packages"
    if site.exists():
        for d in sorted(site.glob("clawd_code-*.dist-info")):
            # 目录名形如 clawd_code-0.60.6.dist-info：不能用 split("-")[1]
            # （会得到 "0.60.6.dist"），必须按正则取版本段。
            m = re.search(r"clawd_code-(\d+\.\d+\.\d+)\.dist-info", d.name)
            if m:
                dist_info = m.group(1)
    return {
        "cli": version,
        "pyproject": pyproject,
        "dist_info": dist_info,
        "consistent": len({v for v in (version, pyproject, dist_info) if v}) == 1,
        "exit_code": res["exit_code"],
    }


def _ruff() -> dict:
    hard = _run([*INTERP_TEST, "-m", "ruff", "check", "src/", "tests/", "--select", "F821,F811,E9"])
    full = _run([*INTERP_TEST, "-m", "ruff", "check", "src/"])
    m = re.search(r"Found (\d+) errors?", "\n".join(full["output_tail"]))
    return {
        "hard_exit_code": hard["exit_code"],
        "hard_status": hard["status"],
        "full_total": int(m.group(1)) if m else 0,
        "full_status": full["status"],
    }


def _silent_except_total() -> dict:
    """直接用 AST 统计，不依赖脚本输出格式（脚本被改也不会静默失效）。"""
    total = 0
    for path in SRC.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and len(node.body) == 1:
                stmt = node.body[0]
                if isinstance(stmt, ast.Pass) or (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is Ellipsis
                ):
                    total += 1
    return {"total": total}


def _parse_kv(tail: list[str], key: str) -> int | None:
    for line in tail:
        if key in line:
            m = re.search(r"(\d+)", line.split(key, 1)[1])
            if m:
                return int(m.group(1))
    return None


def _hard_fail_reasons(data: dict) -> list[str]:
    """返回硬门禁失败原因列表；空列表 = 通过。

    关键原则（2026-10-23 审查教训）：**`None`（没测到）必须算失败，不能算通过**。
    旧版写 `fail not in (0, None)`，于是解析失败得到 None 时判为通过，
    实测出现过"collect exit_code=2 但脚本 exit=0"——一份会说谎的单一取数入口
    比手抄数字更危险。
    """
    reasons: list[str] = []

    if data["ruff"]["hard_exit_code"] != 0:
        reasons.append(f"ruff 硬指标失败（exit={data['ruff']['hard_exit_code']}）")
    if not data["version"]["consistent"]:
        reasons.append(
            f"版本不一致（cli={data['version']['cli']} / pyproject={data['version']['pyproject']}"
            f" / dist-info={data['version']['dist_info']}）"
        )

    collect = data.get("collect")
    if collect is not None:
        if collect.get("exit_code") != 0:
            reasons.append(f"pytest 收集失败（exit={collect.get('exit_code')}, errors={collect.get('errors')}）")
        if collect.get("collected") is None:
            reasons.append("pytest 收集数解析失败（collected=None）")

    sweep = data.get("import_sweep")
    if sweep is not None:
        if sweep.get("status") != "ok":
            reasons.append(f"import_sweep 未正常结束（status={sweep.get('status')}）")
        for key, label in (("fail", "IMPORT-FAIL"), ("import_exit", "IMPORT-EXIT")):
            value = sweep.get(key)
            if value is None:
                reasons.append(f"{label} 未能解析（None 视为失败，不当作通过）")
            elif value != 0:
                reasons.append(f"{label} = {value}（必须为 0）")
        if sweep.get("dep_missing") is None:
            reasons.append("DEP-MISSING 未能解析（None 视为失败）")

    reach = data.get("reachability")
    if reach is not None:
        prod = reach.get("prod_reachable")
        if prod is None:
            reasons.append("生产可达数未能解析（None 视为失败）")
        elif prod < MIN_REACHABLE:
            reasons.append(f"生产可达 {prod} < 基线 {MIN_REACHABLE}")

    cov = data.get("coverage") or {}
    if cov.get("status") == "ok" and cov.get("percent_covered") is not None:
        if cov["percent_covered"] < MIN_COVERAGE_PERCENT:
            reasons.append(
                f"覆盖率 {cov['percent_covered']}% < 阈值 {MIN_COVERAGE_PERCENT}%"
            )

    if reasons:
        data["hard_fail_reasons"] = reasons
        print("\n[baseline] HARD FAIL：")
        for r in reasons:
            print(f"  - {r}")

    return reasons

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None, help="把 JSON 写入该路径")
    ap.add_argument("--with-tests", action="store_true", help="额外跑全量回归（很慢，~数十分钟）")
    ap.add_argument("--quick", action="store_true", help="跳过 collect-only / 导入扫描 / 可达性（最快）")
    args = ap.parse_args()

    modules, lines = _count_modules()
    data: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "host": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
        "code_base": {
            "modules": modules,
            "lines": lines,
            "test_files": len(list(TESTS.rglob("test_*.py"))),
        },
        "version": _version(),
        "ruff": _ruff(),
        "silent_except": _silent_except_total(),
        "coverage": _coverage_metrics(),
    }

    if not args.quick:
        data["collect"] = _collect_metrics()

        sweep_run, sweep_json = _run_to_json(
            [_interp_runtime(), "scripts/import_sweep.py", "--strict-exit"],
            ROOT / ".clawd" / "_baseline_import_sweep.json",
            timeout=900,
        )
        fail_list = sweep_json.get("fail")
        exit_list = sweep_json.get("import_exit")
        dep_list = sweep_json.get("dep_missing")
        data["import_sweep"] = {
            "exit_code": sweep_run["exit_code"],
            "status": sweep_run["status"],
            "fail": len(fail_list) if isinstance(fail_list, list) else None,
            "import_exit": len(exit_list) if isinstance(exit_list, list) else None,
            "dep_missing": len(dep_list) if isinstance(dep_list, list) else None,
            "parse_error": sweep_json.get("_parse_error"),
            "output_tail": sweep_run["output_tail"],
        }

        reach_run, reach_json = _run_to_json(
            [*INTERP_TEST, "scripts/reachability.py"],
            ROOT / ".clawd" / "_baseline_reachability.json",
            timeout=900,
        )
        data["reachability"] = {
            "exit_code": reach_run["exit_code"],
            "status": reach_run["status"],
            "prod_reachable": reach_json.get("prod_reachable"),
            "fully_unreachable": reach_json.get("fully_unreachable"),
            "fully_unreachable_lines": reach_json.get("fully_unreachable_lines"),
            "parse_error": reach_json.get("_parse_error"),
            "output_tail": reach_run["output_tail"],
        }

    if args.with_tests:
        tests = _run([*INTERP_TEST, "-m", "pytest", "tests/", "-q"], timeout=7200)
        joined = "\n".join(tests["output_tail"])
        m = re.search(r"(\d+) passed", joined)
        data["full_tests"] = {
            "exit_code": tests["exit_code"],
            "status": tests["status"],
            "duration_s": tests["duration_s"],
            "passed": int(m.group(1)) if m else None,
            "output_tail": tests["output_tail"],
        }

    # 门禁必须在序列化**之前**算，否则 hard_fail_reasons 进不了 JSON
    reasons = _hard_fail_reasons(data)
    if reasons:
        data["hard_fail_reasons"] = reasons

    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(f"baseline JSON 已写入 {args.out}")
    else:
        print(payload)

    if reasons:
        print("\n[baseline] HARD FAIL：")
        for r in reasons:
            print(f"  - {r}")
    return 1 if reasons else 0


if __name__ == "__main__":
    raise SystemExit(main())


# 说明：本脚本刻意不用 `python` 裸命令（本机不存在），也不读环境变量里的密钥；
# 所有输出都不包含 .env 内容（doctor 的密钥打码由 doctor 自身负责）。
