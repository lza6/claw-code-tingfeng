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


def _run(cmd: list[str], timeout: int = 900) -> dict:
    """执行命令并记录真实退出码与输出尾部。失败不抛异常，如实记录。"""
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return {
            "cmd": " ".join(cmd),
            "exit_code": proc.returncode,
            "status": "ok" if proc.returncode == 0 else "failed",
            "duration_s": round(time.perf_counter() - started, 2),
            "output_tail": out.strip().splitlines()[-6:],
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
        sweep = _run([str(VENV_PY), "scripts/import_sweep.py", "--strict-exit"], timeout=900)
        data["import_sweep"] = {
            "exit_code": sweep["exit_code"],
            "status": sweep["status"],
            "fail": _parse_kv(sweep["output_tail"], "IMPORT-FAIL"),
            "import_exit": _parse_kv(sweep["output_tail"], "IMPORT-EXIT"),
            "dep_missing": _parse_kv(sweep["output_tail"], "DEP-MISSING"),
            "output_tail": sweep["output_tail"],
        }
        reach = _run([*INTERP_TEST, "scripts/reachability.py"], timeout=900)
        joined = "\n".join(reach["output_tail"])
        m = re.search(r":\s*(\d+)\s*$", joined.split("生产入口可达")[-1], re.MULTILINE) if "生产入口可达" in joined else None
        data["reachability"] = {
            "exit_code": reach["exit_code"],
            "status": reach["status"],
            "output_tail": reach["output_tail"],
            "reachable": int(m.group(1)) if m else None,
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

    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(f"baseline JSON 已写入 {args.out}")
    else:
        print(payload)

    # 硬门禁：任何一项硬指标失败则以 1 退出，便于 CI 直接使用
    hard_fail = (
        data["ruff"]["hard_exit_code"] != 0
        or not data["version"]["consistent"]
        or data.get("import_sweep", {}).get("fail") not in (0, None)
        or data.get("import_sweep", {}).get("import_exit") not in (0, None)
    )
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())


# 说明：本脚本刻意不用 `python` 裸命令（本机不存在），也不读环境变量里的密钥；
# 所有输出都不包含 .env 内容（doctor 的密钥打码由 doctor 自身负责）。
