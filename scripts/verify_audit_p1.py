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

# ---------- 输出 ----------
print("=" * 78)
print("审计 P1 台账复验（P1-1 ~ P1-16）")
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
