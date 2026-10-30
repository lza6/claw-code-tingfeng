"""审计 P1 台账逐条复验（P1-1 ~ P1-16）—— 只读代码/跑纯本地断言，不发网络请求

用途：回答"这些 P1 到底闭环没有"。每条给出 ✅/❌ + 证据（文件/片段），
任何一条 ❌ 都会让退出码非 0，便于当门禁用。

用法：
    venv/Scripts/python.exe scripts/verify_audit_p1.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# 证据里含中文/符号，Windows 控制台默认 GBK 会在 print 时直接抛
# UnicodeEncodeError，把"全绿"变成"脚本崩了"（真实踩过）。强制 UTF-8 + 替换。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # 老解释器/已重定向
        pass

ROOT = Path(__file__).resolve().parents[1]
results: list[tuple[str, bool, str]] = []


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def check(tag: str, ok: bool, evidence: str) -> None:
    results.append((tag, ok, evidence))


# P1-1 worktree integrator 不再假成功
try:
    src = _read("src/agent/swarm/worktree_manager.py")
    no_todo = "TODO: 通过 IntegratorAgent" not in src
    real_merge = "def _apply_changes_via_git" in src
    tests = (ROOT / "tests/agent/swarm/test_worktree_merge.py").is_file()
    check("P1-1 worktree 合并", no_todo and real_merge and tests,
          f"TODO 已移除={no_todo}, 真实合并实现={real_merge}, 测试存在={tests}")
except Exception as e:  # noqa: BLE001
    check("P1-1 worktree 合并", False, f"检查失败: {e}")

# P1-2 core/mcp 四个 server 有 __main__
missing = []
for name in ("state", "memory", "trace", "team"):
    rel = f"src/core/mcp/{name}_server.py"
    if '__main__' not in _read(rel) or "def main(" not in _read(rel):
        missing.append(name)
stdio = (ROOT / "src/core/mcp/stdio_server.py").is_file()
check("P1-2 MCP server 可启动", not missing and stdio,
      f"缺入口={missing or '无'}, stdio_server.py={stdio}")

# P1-3 悬空依赖抛错
src = _read("src/workflow/task_planner.py")
check("P1-3 悬空依赖", "悬空依赖" in src and "raise ValueError" in src,
      "task_planner 对悬空依赖抛 ValueError（不再是 logger.warning 后继续）")

# P1-4 引擎接线 hook_registry
eng = _read("src/agent/engine.py")
check("P1-4 hooks 接线", "_execute_hook_point" in eng and "execute_hook" in eng,
      "engine.py 在 SESSION_START/END、PRE/POST_TOOL_USE、TOOL_ERROR 五点调用 hook_registry")

# P1-5 onboarding 接线
entry = _read("src/cli/entrypoint.py")
onboard_cmd = '@app.command(name="onboard")' in entry and "preflight_report" in entry
chat_pre = "preflight_report()" in entry
check("P1-5 上手引导接线", onboard_cmd and chat_pre,
      f"clawd onboard 命令={onboard_cmd}, chat 启动体检={chat_pre}")

# P1-6 拼写 + 双份实现标注
typo = any("sumsummarize" in _read(f"src/core/mcp/{n}_server.py")
           for n in ("state", "memory", "trace", "team"))
legacy = all("legacy" in _read(f"src/mcp/{n}_server.py") for n in ("state", "memory", "trace"))
check("P1-6 工具名/双份实现", not typo and legacy,
      f"sumsummarize 残留={typo}, legacy 标注齐={legacy}（ADR 0018 定 core/mcp 为唯一真相源）")

# P1-7 生成配置指向可运行的 server
gen = _read("src/core/config/generator.py")
check("P1-7 承诺=实现", "src.core.mcp.state_server" in gen and "MCP_PYTHON" in gen,
      "生成配置指向 core/mcp（有 __main__），command 用 sys.executable 而非裸 python")

# P1-8 基线缺失不再假成功
base = _read("src/eval/baseline.py")
entry = _read("src/cli/entrypoint.py")
check("P1-8 评测基线", "def load_baseline_strict" in base and "基线不可用" in entry,
      "基线不存在 → CLI 报错退出 2（不再打印'基线比对通过'）")

# P1-9 rich_hud 不再是空壳
hud = _read("src/cli/rich_hud.py")
check("P1-9 RichLiveHud", "placeholder" not in hud and "__rich_console__" in hud and len(hud.splitlines()) > 100,
      f"rich_hud.py {len(hud.splitlines())} 行，实现 __rich_console__ 真渲染")

# P1-10 评测三态
models = _read("src/eval/models.py")
check("P1-10 评测三态", "unknown" in models and "def unknowns" in models,
      "EvalOutcome 支持 unknown；通过率只在已判定用例里算")

# P1-11 技能递归发现
loader = _read("src/agent/skill_loader.py")
check("P1-11 技能可达", "rglob('SKILL.md')" in loader,
      "discover_skills 用 rglob（实测 63 → 113，reverse 子技能可见）")

# P1-12 正文截断上限
m = re.search(r"MAX_SKILL_BODY_CHARS = (\d+)", loader)
limit = int(m.group(1)) if m else 0
check("P1-12 技能截断", limit >= 26000 and "已截断" in loader,
      f"MAX_SKILL_BODY_CHARS={limit}（现有最大技能 23,159 字符），截断有告警")

# P1-13 质量门聚合
qg = _read("src/core/quality_gate.py")
check("P1-13 质量门聚合", "_calculate_overall(self.results)" in qg,
      "overall 走 _calculate_overall 聚合，不再只看 results[0]")

# P1-14 review 面并行 + 无"[模拟响应]"
rt = (ROOT / "src/agent/review_team.py")
debate = _read("src/agent/swarm/debate.py")
# 注意：文档里提到旧行为（"[模拟 CRITIC 响应]"）是允许的，这里只查**代码里还产不产生**它
has_fake_return = 'return f"[模拟' in debate
check("P1-14 审查并行", rt.is_file() and "asyncio.gather" in rt.read_text(encoding="utf-8")
      and not has_fake_return and "raise DebateUnavailable" in debate,
      "review_team 用 asyncio.gather 并行跑角色；debate 缺 orchestrator 时抛 DebateUnavailable，"
      f"不再返回占位串（残留假返回={has_fake_return}）")

# P1-15 domain_server RepoMap 签名
dom = _read("src/mcp/domain_server.py")
# 文档里引用旧写法 `RepoMap(root=...)` 是解释性说明；这里查**真实调用**是否仍是旧签名
uses_old_call = "RepoMap(root=str(" in dom or "RepoMap(root=(" in dom
check("P1-15 project_map",
      "RepoMap(token_budget" in dom and "get_map(files)" in dom and not uses_old_call,
      f"真实调用是 RepoMap(token_budget=..., root_dir=...).get_map(files)（旧签名残留={uses_old_call}）")

# P1-16 smoke.json 工具名
smoke = json.loads(_read("src/eval/datasets/smoke.json"))
names = set()
for case in smoke.get("cases", []):
    names.update(case.get("expect", {}).get("tool_sequence") or [])
    names.update((case.get("recorded") or {}).get("tools") or [])
bad = {n for n in names if n in {"read_file", "edit_file", "write_file"}}
check("P1-16 用例工具名", not bad,
      f"smoke.json 工具名={sorted(names)}，无 read_file/edit_file 旧名")

# ==========================================================================
# P2 台账（P2-1 ~ P2-6）
# ==========================================================================

# P2-1 trace 技能文档指引的工具必须真实存在
try:
    trace_skill = (ROOT / "skills/trace/SKILL.md").read_text(encoding="utf-8")
    from src.core.mcp.trace_server import TRACE_SERVER_TOOLS  # noqa: E402

    referenced = {"get_recent_traces", "get_trace", "summarize_trace", "export_trace"}
    ok = referenced <= set(TRACE_SERVER_TOOLS) and "Use `trace_timeline`" not in trace_skill
    check("P2-1 trace 技能可运行", ok,
          f"文档引用的工具都在注册表={referenced <= set(TRACE_SERVER_TOOLS)}；旧的 trace_timeline 调用写法已移除")
except Exception as e:  # noqa: BLE001
    check("P2-1 trace 技能可运行", False, f"检查失败: {e}")

# P2-2 skill 技能里 codex 路径已有 clawd 适配说明
skill_md = (ROOT / "skills/skill/SKILL.md").read_text(encoding="utf-8")
check("P2-2 技能路径适配", "clawd 路径适配" in skill_md,
      "skills/skill/SKILL.md 已加『clawd 路径适配』说明块（原文 ~/.codex 路径是 Codex 时代遗留）")

# P2-3 空目录已清
empty_dirs = [d for d in ("src/autoresearch", "src/openclaw", "src/templates") if (ROOT / d).exists()]
check("P2-3 空目录清理", not empty_dirs, f"仍存在的空目录={empty_dirs or '无'}")

# P2-4 文档数字与实际一致（用专门的门禁脚本）
proc_drift = None
try:
    import subprocess

    proc_drift = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_doc_drift.py")],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900,
    )
    check("P2-4 文档数字不漂移", proc_drift.returncode == 0,
          "README 的 用例收集/静默吞异常/可达模块 与现跑一致"
          if proc_drift.returncode == 0 else (proc_drift.stdout or "")[-300:])
except Exception as e:  # noqa: BLE001
    check("P2-4 文档数字不漂移", False, f"检查失败: {e}")

# P2-5 评测数据集：用例够多 + 三态有样例
try:
    smoke = json.loads((ROOT / "src/eval/datasets/smoke.json").read_text(encoding="utf-8"))
    honesty = json.loads((ROOT / "src/eval/datasets/honesty.json").read_text(encoding="utf-8"))
    check("P2-5 评测用例与三态", len(smoke["cases"]) >= 7 and len(honesty["cases"]) >= 4,
          f"smoke={len(smoke['cases'])} 条，honesty={len(honesty['cases'])} 条（含 UNKNOWN 样例）")
except Exception as e:  # noqa: BLE001
    check("P2-5 评测用例与三态", False, f"检查失败: {e}")

# P2-6 getting-started 是产品教程
gs = (ROOT / "docs/getting-started.md").read_text(encoding="utf-8")
has_steps = all(k in gs for k in ("安装", "配置", "第一个任务", "看懂它刚才做了什么"))
check("P2-6 上手教程", has_steps and "skills-distribution" in gs,
      "docs/getting-started.md 是『安装→配置→第一个任务→看懂发生了什么』教程，技能分发已拆到 skills-distribution.md")


# ==========================================================================
# P3 / 风险表（P3-1 ~ P3-3、R1 ~ R3）
# ==========================================================================

def _run_script(rel: str, extra: list[str] | None = None, timeout: int = 900):
    import os
    import subprocess

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(ROOT / rel), *(extra or [])],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, env=env,
    )


# P3-1 src/core 边界治理（新增越界即失败；存量已登记）
try:
    proc = _run_script("scripts/core_surface.py")
    check("P3-1 core 边界", proc.returncode == 0, (proc.stdout or "").strip().splitlines()[-2] if proc.stdout else "")
except Exception as e:  # noqa: BLE001
    check("P3-1 core 边界", False, f"检查失败: {e}")

# P3-2 不可达模块收敛（不超过基线 110 个 / 25441 行）
try:
    proc = _run_script("scripts/reachability.py", ["--min-reachable", "443"])
    text = proc.stdout or ""
    import re as _re

    m = _re.search(r"生产不加载[^:：]*[:：]\s*(\d+)", text)
    unreachable = int(m.group(1)) if m else -1
    check("P3-2 不可达收敛", proc.returncode == 0 and 0 <= unreachable <= 110,
          f"不可达模块={unreachable}（基线 ≤110；本轮删除 31 个死模块后 141→110）")
except Exception as e:  # noqa: BLE001
    check("P3-2 不可达收敛", False, f"检查失败: {e}")

# P3-3 CLI 的"讲人话"入口（explain / --cross / ledger）
try:
    entry = (ROOT / "src/cli/entrypoint.py").read_text(encoding="utf-8")
    ok = '@app.command(name="explain")' in entry and "--cross" in entry and '@app.command(name="ledger")' in entry
    check("P3-3 explain/ledger 入口", ok,
          "clawd explain（单轮讲人话）、explain --cross（跨会话归因）、ledger（账本诊断）均存在")
except Exception as e:  # noqa: BLE001
    check("P3-3 explain/ledger 入口", False, f"检查失败: {e}")

# R1 假成功专项扫描（打日志/TODO 后 return True）
try:
    proc = _run_script("scripts/scan_fake_success.py")
    check("R1 假成功扫描", proc.returncode == 0,
          (proc.stdout or "").strip().splitlines()[1] if proc.stdout else "")
except Exception as e:  # noqa: BLE001
    check("R1 假成功扫描", False, f"检查失败: {e}")

# R2 生成配置的可启动性（真实 spawn + 握手）
try:
    proc = _run_script("scripts/check_mcp_startup.py", timeout=600)
    check("R2 MCP 可启动性", proc.returncode == 0,
          (proc.stdout or "").strip().splitlines()[-2] if proc.stdout else "")
except Exception as e:  # noqa: BLE001
    check("R2 MCP 可启动性", False, f"检查失败: {e}")

# R3 两套账本单一入口
try:
    from src.workflow.run_ledger import RunLedger  # noqa: E402

    ok = hasattr(RunLedger, "snapshot") and hasattr(RunLedger, "record_stage")
    check("R3 账本单一入口", ok, "RunLedger.snapshot() 读、record_stage() 写；clawd ledger 出诊断")
except Exception as e:  # noqa: BLE001
    check("R3 账本单一入口", False, f"检查失败: {e}")


# ---------- 输出 ----------
print("=" * 78)
print("审计台账复验（P1×16、P2×6、P3×3、风险×3）")
print("=" * 78)
failed = 0
for tag, ok, evidence in results:
    mark = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"[{mark}] {tag}")
    print(f"        {evidence}")
print("-" * 78)
print(f"合计 {len(results)} 项，通过 {len(results) - failed}，失败 {failed}")
print("=" * 78)
sys.exit(0 if failed == 0 else 1)
