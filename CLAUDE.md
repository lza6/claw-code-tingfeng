# Clawd Code — AI Programming Agent Framework

> ## ⚠️ 改动本项目之前，先读这三处
>
> 1. **`workflow_status.md`** — 上一轮改了什么、验证到哪一步、什么还没做
> 2. **`skills/clawd-change-workflow/SKILL.md`** — 本项目的变更流程、已知陷阱、
>    验收标准。**任何新增功能 / 修 bug / 进入陌生区域前必须加载**
> 3. **`计划书/`** 下最新文档 — 当前计划与缺陷台账
> 4. **`docs/MAINTENANCE.md`** — 新增 Provider / Tool / CLI 的逐步 SOP、发布检查单、排障索引
> 5. **`docs/adr/README.md`** — 会影响后续判断的架构决策（含"为什么这么做"）
>
> **然后做文档保鲜检查**：这些文档会过时。对读到的每条具体断言
> （"X 尚未实现"、"文件在 Y"、"覆盖率约 N%"），用真实代码验证后再动手。
> 判定规则与实例见上述 skill 的 Phase 1。
>
> **最短验证路径**（改动涉及 LLM / 工具 / 配置 / 导入结构时）：
> ```bash
> venv/Scripts/python.exe scripts/e2e_smoke.py                  # 真实端点 E2E，退出码 0 才算通过
> py -3.10 -m pytest tests/contracts/ -q                         # 公共 API 契约
> py -3.10 -m pytest tests/ --collect-only -q                    # 期望 0 errors（实测 5007 / 5.1s）
> venv/Scripts/python.exe scripts/import_sweep.py --strict-exit  # IMPORT-FAIL 0 且 IMPORT-EXIT 0
> py -3.10 -m ruff check src/ tests/ --select F821,F811,E9        # 期望 All checks passed
> venv/Scripts/python.exe scripts/reachability.py --min-reachable 443  # 删码后可达数不得下降
> venv/Scripts/python.exe scripts/check_silent_except.py --fail-over 158  # 静默吞异常只降不升
> # 桌面端出包（改了 src/ prompts/ personas/ desktop/web/ 都必须重跑，否则装出来的还是旧代码）
> venv/Scripts/python.exe scripts/prepare_host_bundle.py  # 必须看到 [5/5] 自检全过（缺依赖会自动补齐）
> pwsh -NoProfile -File scripts/build_desktop_signed.ps1 -SelfSigned
> ```
>
> **审计台账 + 风险门禁（一轮全跑，约 3 分钟）**：
> ```bash
> venv/Scripts/python.exe scripts/verify_audit_p1.py        # P1×16 + P2×6 + P3×3 + 风险×3 = 28 条，全绿才算数
> venv/Scripts/python.exe scripts/scan_fake_success.py      # 「打日志/TODO 后 return True」专项，期望 0 命中
> venv/Scripts/python.exe scripts/check_mcp_startup.py      # 生成配置里每个 MCP server 真 spawn + 握手
> venv/Scripts/python.exe scripts/core_surface.py           # core 不得 import 上层；存量在 core_surface_allow.json
> venv/Scripts/python.exe scripts/check_doc_drift.py        # README 数字必须与现跑一致
> ```
>
> 日常快检（约 4 分钟，不含 slow 层约 410s）：
> `py -3.10 -m pytest tests/ -q -m "not slow"` · 全量 `py -3.10 -m pytest tests/ -q`（约 13 分钟）
> **取一次全部指标**：`py -3.10 scripts/baseline.py --out .clawd/baseline.json`
> （17 项指标一条命令出数；文档里的数字以它为准，不要手抄）
>
> **解释器矩阵**（本机 `python` 命令不存在，别照抄）：
> `venv/Scripts/python.exe` = 运行依赖 + **已装 pytest/ruff/coverage**（首选）；
> `py -3.10` = 测试与 lint 工具齐全；`py`（默认 3.14）缺 `loguru`，**不要用**。
>
> **本项目的硬指标**（v0.57.0 起作为基线，现已全部接入 CI）：
> `F821 = 0` · `F811 = 0` · `IMPORT-FAIL = 0` · `IMPORT-EXIT = 0` · 生产可达 ≥ 443 · 静默吞异常 ≤ **158** · 覆盖率 ≥ **60%**。
> 任何一项回升都视为回归，先修再谈其他。
>
> **门禁 2026-10-29 已收紧**（原 172 / 47，远低于实际 → 掉 15 个点仍能全绿，尺子失效）：
> 静默吞异常 172→162→**158**、覆盖率 `fail_under` 47→**60**。单一来源分别在
> `scripts/hard_metrics.py` 与 `pyproject.toml`，改一处必须同步另一处（有测试守着）。

## Project Overview

Clawd Code is a comprehensive AI-powered coding agent framework written in Python. It provides multi-agent collaboration, self-healing, codebase awareness (World Model), enterprise-grade RAG, and a full workflow engine.

**GoalX Integration (v2026-04-13):**
- Durable Surfaces: 9 canonical surfaces (charter, obligation_model, control_state, coordination_state, assurance_plan, evidence_log, objective_contract, status_summary, freshness_state)
- Budget Guard: Resource safety monitoring (PSI, RSS, Host pressure) + dynamic adjustment
- Worktree Isolation: Git worktree-based parallel execution with explicit merge boundaries (keep/integrate)
- Integration Engine: `keep_session`, `keep_to_source`, `partial_adopt` semantics
- Intent Routing: DELIVER, EXPLORE, EVOLVE, IMPLEMENT, DEBATE
- Debate Mode: From saved runs with evidence-based challenge/review
- Memory Seed & Promote: Project bootstrap memory + short-to-long-term memory promotion
- Resource Profile: Detailed host/PID/memory/disk/load profiling with history tracking

**Aider Integration (v0.50.0 - 2026-04-08):**
- 18+ Aider-style commands (/add, /drop, /run, /test, /git, etc.)
- 10 edit formats (editblock, wholefile, udiff, patch, etc.)
- 25+ model aliases with metadata caching
- RepoMap code understanding
- Tree-sitter syntax parsing
- 20+ LLM exception types handling
- Message role sanitization
- File pattern filtering (gitignore)
- Version checking (PyPI)
- 34 new integration tests

**Oh-My-Codex Integration (v2026-04-14):**
- Intent Router: 关键词检测与技能自动激活 (src/agent/intent_router.py)
- Keyword Registry: 40+ 技能关键词注册表 (src/agent/keyword_registry.py)
- Mode State: 独占模式互斥检查、跨会话恢复 (src/workflow/mode_state.py)
- Pipeline Orchestrator: RALPLAN -> team-exec -> ralph 管道 (src/workflow/pipeline_orchestrator.py)
- Session History Search: 历史会话检索 (src/workflow/session_history_search.py)
- Team Persistence: 团队状态持久化 (src/workflow/team_persistence.py)
- Ralph Ledger: RALPH 进度账本与视觉反馈 (src/workflow/ralph_ledger.py)
- Keyword Registry: 40+ 技能关键词注册表 (src/agent/keyword_registry.py)
- Mode State: 独占模式互斥检查、跨会话恢复 (src/workflow/mode_state.py)
- Pipeline Orchestrator: RALPLAN -> team-exec -> ralph 管道 (src/workflow/pipeline_orchestrator.py)
- Session History Search: 历史会话检索 (src/workflow/session_history_search.py)
- Team Persistence: 团队状态持久化 (src/workflow/team_persistence.py)
- Ralph Ledger: RALPH 进度账本与视觉反馈 (src/workflow/ralph_ledger.py)
- Task Analyzer: 任务规模检测 (small/medium/large/heavy)
- Code Simplifier: 自动代码简化钩子 (src/tools_runtime/code_simplifier.py)
- RALPH Loop: 持久化循环执行技能 (skills/ralph_loop/)
- Team Execution: 并行代理执行增强
- Pipeline Orchestrator: RALPLAN -> team-exec -> ralph-verify 管道 (src/workflow/pipeline_*.py)
- Mode State: 管道/团队/技能模式状态持久化 + 独占模式互斥检查 (src/workflow/mode_state.py)
- Ralph Progress Ledger: 视觉反馈记录 + 进度账本 (src/workflow/ralph_ledger.py)
- Agent Prompts: 34 个 Agent Prompt 模板库 (prompts/agents/)
- Agent Definitions: 40+ Agent 角色定义 (src/agent/definitions.py)
- Agent Prompts: 34 个 Agent Prompt 模板库 (prompts/agents/)
- Agent Definitions: 40+ Agent 角色定义 (src/agent/definitions.py)

## Tech Stack

- **Language:** Python 3.10+
- **Package Manager:** pip / pyproject.toml
- **Testing:** pytest（**2026-10-29 实测：5,007 收集用例 / 0 errors / 5.1s**；`not slow` 全量 **4,979 passed / 0 failed**（8~14 分钟，波动较大）；覆盖率 **62.39%**，`fail_under = 60` 已生效 —— 见 `pyproject.toml` 的 `[tool.coverage.report]`）
  > 注：覆盖率数字请以 `pytest --cov=src` 的实际输出为准。历史上此处长期
  > 虚报为 "1414 用例 / ~50%"、后来又写成 "2857 用例 / 19.5%"，
  > 与实测相差 2 倍以上。指标不要写死在文档里。
- **Linting:** ruff
- **Type Checking:** mypy (optional)
- **Containerization:** Docker + docker-compose
- **CI/CD:** GitHub Actions
- **Git Integration:** gitpython (undo, diff, commit attribution, co-authored-by)

## Project Structure

```
src/                    → Main source code
├── agent/              → Agent engine + multi-agent swarm system
├── brain/              → World Model (codebase awareness)
├── cli/                → REPL interface + TUI components
├── core/               → Settings, events, exceptions, patch engine, git integration
│   ├── important_files.py  # File importance detection (from Aider)
│   └── args_parser.py       # Enhanced CLI argument parsing
├── llm/                → Multi-provider LLM abstraction (9 providers)
│   ├── exception_handler.py # LLM exception classification
│   ├── message_handler.py  # Message role sanitization
│   ├── model_manager.py    # Model aliases & metadata
│   ├── openrouter_manager.py # OpenRouter integration
│   └── prompts/            # Prompt templates
├── memory/             → Enterprise long-term memory (SQLite, async)
├── rag/                → Trigram index, text indexer, dependency graph
│   ├── repo_map.py        # Code map (from Aider)
│   └── tree_sitter_syntax.py # Syntax parsing
├── self_healing/       → Auto error detection and AI-driven repair
├── tools_runtime/      → Tool execution (bash, file, grep, glob, AI comment watcher)
├── workflow/           → 5-phase execution pipeline
└── utils/              → Shared utilities (from Aider)
    ├── diff_utils.py       # Diff & progress bar
    ├── version_check.py   # PyPI version check
    ├── file_patterns.py    # Gitignore patterns
    ├── urls.py            # Documentation URLs
    ├── report.py          # Bug reporter
    ├── deprecated_args.py # Deprecated CLI args
    ├── image_utils.py     # Image file detection
    ├── arg_formatter.py  # CLI help formatters
    ├── analytics.py       # Telemetry (disabled by default)
    ├── voice.py          # Whisper voice input
    ├── scrape.py        # Web scraping
    ├── watch.py          # File watcher with AI comment detection
    └── onboarding.py     # New user onboarding

skills/                 → 21 engineering skills (SKILL.md per directory)
agents/                 → Agent personas (code-reviewer, security-auditor, test-engineer)
hooks/                  → Session lifecycle hooks (simplify-ignore protection)
references/             → Checklists (accessibility, performance, security, testing)
.claude/commands/       → Slash commands for Claude Code
tests/                  → Test suite
```

## Commands

```bash
# Development
python -m pytest tests/ -v --tb=short    # Run tests
python -m pytest tests/ --tb=short        # Run tests (short output)
ruff check src/                            # Lint
ruff format src/                           # Format

# Run the agent
python -m src                              # 规范入口（= clawd，Typer CLI）
python -m src chat                          # Chat mode
python -m src doctor                        # Environment diagnostics
python -m src run "目标"                     # 5 阶段工作流引擎
python -m src workflow autopilot "目标"       # 管道命令组（ralph/ralplan/team/autopilot）
python -m src.main                          # 历史 argparse 入口（兼容保留，命令集更小）
```

## Conventions

- Python code follows PEP 8 with ruff enforcement
- Test files mirror source structure: `tests/<module>/`
- Settings use 6-layer priority: defaults → .env → runtime → CLI → file → API
- Feature flags managed in `.clawd/features.json`
- Agent swarm roles defined in `src/agent/swarm/roles.py`
- LLM providers configured via `LLM_PROVIDER` env var or settings
- Skills use YAML frontmatter with `name` and `description` fields
- Skill description starts with what it does (third person), followed by trigger conditions ("Use when...")
- Every skill has: Overview, When to Use, Process, Common Rationalizations, Red Flags, Verification
- References are in `references/`, not inside skill directories
- Supporting files only created when content exceeds 100 lines

## Slash Commands (Claude Code)

| Command | Purpose |
|---------|---------|
| `/spec` | Spec-driven development |
| `/plan` | Task planning with dependency graph |
| `/build` | Incremental TDD implementation |
| `/test` | TDD workflow (RED/GREEN/REFACTOR) |
| `/review` | Five-axis code review |
| `/code-simplify` | Code simplification |
| `/ship` | Pre-launch checklist and deployment prep |
| `/undo` | Undo last AI commit (from Aider) |
| `/diff` | Show uncommitted changes (from Aider) |
| `/compact` | Compress conversation context |
| `/format` | Switch edit format (Aider integration) |
| `/add` | Add file to chat (Aider) |
| `/drop` | Remove file from chat (Aider) |
| `/test` | Run tests (Aider) |
| `/lint` | Run linter (Aider) |
| `/git` | Git shortcuts (Aider) |

## Engineering Skills

Skills are located in `skills/<name>/SKILL.md`. Each skill follows a consistent anatomy:

**Project-specific（本仓库专用）:** **clawd-change-workflow** — 本项目的变更流程、文档保鲜检查、已知陷阱、验收标准。**进入本项目前必读。**
**Define:** idea-refine, spec-driven-development
**Meta:** using-agent-skills
**Plan:** planning-and-task-breakdown
**Build:** incremental-implementation, test-driven-development, context-engineering, frontend-ui-engineering, api-and-interface-design
**Verify:** browser-testing-with-devtools, debugging-and-error-recovery
**Review:** code-review-and-quality, code-simplification, security-and-hardening, performance-optimization
**Ship:** git-workflow-and-versioning, ci-cd-and-automation, deprecation-and-migration, documentation-and-adrs, shipping-and-launch

## Agent Personas

Three specialist personas in `agents/`:
- **code-reviewer.md** — Staff Engineer; five-axis review (correctness, readability, architecture, security, performance)
- **security-auditor.md** — Security Engineer; vulnerability detection, OWASP assessment
- **test-engineer.md** — QA Specialist; test strategy, coverage analysis, Prove-It pattern

## Boundaries

- Always: Run tests after code changes
- Always: Follow the existing code patterns and architecture
- Always: Use the patch engine for declarative code modifications
- Never: Commit secrets or API keys
- Never: Modify `.env` files with real credentials
- Never: Skip error handling — use the structured error codes from `src/core/exceptions.py`
- Never: Add dependencies without updating `requirements.txt` and `pyproject.toml`

<!-- autoskills:start -->

Summary generated by `autoskills`. Check the full files inside `.claude/skills`.

## Accessibility (a11y)

Audit and improve web accessibility following WCAG 2.2 guidelines. Use when asked to "improve accessibility", "a11y audit", "WCAG compliance", "screen reader support", "keyboard navigation", or "make accessible".

- `.claude/skills/accessibility/SKILL.md`
- `.claude/skills/accessibility/references/A11Y-PATTERNS.md`: Practical, copy-paste-ready patterns for common accessibility requirements. Each pattern is self-contained and linked from the main [SKILL.md](../SKILL.md).
- `.claude/skills/accessibility/references/WCAG.md`

## Design Thinking

Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications (examples include websites, landing pages, dashboards, React components, HTML/CSS layouts, or when styling/beaut...

- `.claude/skills/frontend-design/SKILL.md`

## Python Background Jobs & Task Queues

Python background job patterns including task queues, workers, and event-driven architecture. Use when implementing async task processing, job queues, long-running operations, or decoupling work from request/response cycles.

- `.claude/skills/python-background-jobs/SKILL.md`

## Python Code Executor

Execute Python code in a safe sandboxed environment via [inference.sh](https://inference.sh). Pre-installed: NumPy, Pandas, Matplotlib, requests, BeautifulSoup, Selenium, Playwright, MoviePy, Pillow, OpenCV, trimesh, and 100+ more libraries. Use for: data processing, web scraping, image manipulat...

- `.claude/skills/python-executor/SKILL.md`

## Python Testing Patterns

Implement comprehensive testing strategies with pytest, fixtures, mocking, and test-driven development. Use when writing Python tests, setting up test suites, or implementing testing best practices.

- `.claude/skills/python-testing-patterns/SKILL.md`
- `.claude/skills/python-testing-patterns/references/advanced-patterns.md`: Advanced testing patterns including async code, monkeypatching, temporary files, conftest setup, property-based testing, database testing, CI/CD integration, and configuration.

## SEO optimization

Optimize for search engine visibility and ranking. Use when asked to "improve SEO", "optimize for search", "fix meta tags", "add structured data", "sitemap optimization", or "search engine optimization".

- `.claude/skills/seo/SKILL.md`

<!-- autoskills:end -->
