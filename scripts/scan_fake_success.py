"""「假成功」专项扫描：找出 `return True` 前面只有 TODO / 只有日志的函数

动机（审计 2.4 风险表第一条）：
    "任何 return True 前有 TODO / log-only 的分支"都可能是在**报告成功但什么都没做**。
    v0.76.5 修的 worktree `integrator` 就是这一类（打一行日志然后 return True）。

判定（刻意保守，只报"很像假成功"的）：
1. 函数里出现 `return True`，且它**前面 3 行内**有 TODO / FIXME / 占位 / 暂时 / 未实现 注释或字符串；
2. 函数的函数体除了 docstring、`logger.*`/`print`、`pass`、`return True/False/None` 之外**没有任何实际语句**；
3. 函数体只有 `return True`（连日志都没有）。

用法：
    venv/Scripts/python.exe scripts/scan_fake_success.py            # 报告，命中即退出 1
    venv/Scripts/python.exe scripts/scan_fake_success.py --json      # 机器可读
    venv/Scripts/python.exe scripts/scan_fake_success.py --allow scripts/fake_success_allow.json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("src",)
DEFAULT_ALLOW = ROOT / "scripts" / "fake_success_allow.json"
SUSPICIOUS_WORDS = ("TODO", "FIXME", "占位", "暂时", "未实现", "placeholder", "not implemented", "stub")
LOG_CALL_HINTS = ("logger", "logging", "log.", "print", "warn", "debug", "info", "warning", "error")

#: 常量能力声明（"这个后端可用吗 / 支持流式吗"）不是"完成判定"，返回 True 是它的语义
PREDICATE_PREFIXES = ("available", "supports_", "can_", "is_", "has_", "validate", "enabled")


def _is_noop_statement(node: ast.stmt) -> bool:
    """docstring / pass / 纯日志 / 纯 return 视为"没干活" """
    if isinstance(node, ast.Pass):
        return True
    if isinstance(node, ast.Expr):
        value = node.value
        if isinstance(value, ast.Constant):  # docstring 或裸字符串
            return True
        if isinstance(value, ast.Call):
            target = value.func
            name = ""
            if isinstance(target, ast.Name):
                name = target.id
            elif isinstance(target, ast.Attribute):
                name = target.attr
            return any(hint in name.lower() for hint in LOG_CALL_HINTS)
    if isinstance(node, ast.Return):
        return True
    return False


def _scan_function(fn: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> list[dict]:
    findings: list[dict] = []
    if fn.name.startswith(PREDICATE_PREFIXES):
        return findings  # 能力谓词，返回常量 True 属正常语义
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # 去掉 docstring

    has_true_return = any(
        isinstance(node, ast.Return)
        and isinstance(node.value, ast.Constant)
        and node.value.value is True
        for node in ast.walk(fn)
    )
    if not has_true_return:
        return findings

    # 规则 3：函数体只有 return True
    real_body = [node for node in body if not _is_noop_statement(node)]
    if not real_body:
        returns_true_only = all(
            isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value is True
            for node in body
        ) or any(
            isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value is True
            for node in body
        )
        if returns_true_only:
            findings.append({
                "line": fn.lineno,
                "function": fn.name,
                "reason": "函数体只有日志/return True，没有任何实际语句",
            })
        return findings

    # 规则 1：return True 前 3 行内有 TODO 类字样
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value is True):
            continue
        start = max(1, node.lineno - 3)
        context = "\n".join(lines[start - 1:node.lineno])
        for word in SUSPICIOUS_WORDS:
            if word.lower() in context.lower():
                findings.append({
                    "line": node.lineno,
                    "function": fn.name,
                    "reason": f"return True 前 3 行出现「{word}」",
                })
                break
    return findings


def scan(path: Path) -> list[dict]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []
    lines = source.splitlines()
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for finding in _scan_function(node, lines):
                finding["file"] = str(path.relative_to(ROOT)).replace("\\", "/")
                out.append(finding)
    return out


def load_allow(path: Path) -> set[tuple[str, str]]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {(item.get("file", ""), item.get("function", "")) for item in data.get("allowed", [])}


def main() -> int:
    ap = argparse.ArgumentParser(description="假成功专项扫描")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--allow", default=str(DEFAULT_ALLOW), help="允许清单 JSON")
    args = ap.parse_args()

    findings: list[dict] = []
    for base in SCAN_DIRS:
        for path in sorted((ROOT / base).rglob("*.py")):
            findings.extend(scan(path))

    allowed = load_allow(Path(args.allow))
    kept = [f for f in findings if (f["file"], f["function"]) not in allowed]
    ignored = [f for f in findings if (f["file"], f["function"]) in allowed]

    if args.json:
        print(json.dumps({"findings": kept, "allowed": ignored}, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print(f"假成功扫描：命中 {len(kept)} 处（另有 {len(ignored)} 处已审阅允许）")
        print("=" * 70)
        for item in kept:
            print(f"[{item['file']}:{item['line']}] {item['function']}() — {item['reason']}")
        if not kept:
            print("未发现「打日志/TODO 后直接 return True」的可疑分支")
        print("=" * 70)
    return 0 if not kept else 1


if __name__ == "__main__":
    sys.exit(main())
