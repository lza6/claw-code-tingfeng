# Clawd Code — AI Programming Agent Framework

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

## Tech Stack

- **Language:** Python 3.10+
- **Package Manager:** pip / pyproject.toml
- **Testing:** pytest (1414 test cases, ~50% coverage, target 60%)
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
    └── test_aider_integration.py # Integration tests for Aider modules

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
python -m src.main                         # Launch REPL
python -m src.main chat                    # Chat mode
python -m src.main doctor                  # Environment diagnostics
python -m src.main workflow                # Workflow engine
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
