# Backend Architecture

<!-- Generated: 2026-04-18 | Files scanned: 695 | Token estimate: ~800 -->

## CLI Command Structure

**Entry point**: `src/main.py`
**Command registry**: `src/cli/command_registry.py`

### Core Commands
```
python -m src.main          # Launch REPL
python -m src.main chat     # Chat mode
python -m src.main doctor   # Environment diagnostics
python -m src.main workflow # Workflow engine
```

### Aider-style Commands (from integration)
- `/add` - Add file to chat
- `/drop` - Remove file from chat
- `/run` - Execute code/command
- `/test` - Run tests
- `/git` - Git shortcuts
- `/diff` - Show uncommitted changes
- `/undo` - Undo last AI commit
- `/compact` - Compress conversation context
- `/format` - Switch edit format
- `/spec` - Spec-driven development
- `/plan` - Task planning with dependency graph
- `/build` - Incremental TDD implementation
- `/review` - Five-axis code review

## Agent System Architecture

```
Agent Lifecycle:
BaseAgent → Specialized Roles → Swarm Orchestration

Core Components:
├── BaseAgent (base_agent.py)
│   ├── message handling
│   ├── persistence setup
│   └── role-based system prompts
├── Agent Roles (roles.py)
│   ├── PLANNER
│   ├── ARCHITECT
│   ├── CRITIC
│   ├── EXECUTOR
│   └── AUDITOR
├── Swarm Engine (engine.py)
│   ├── task scheduling
│   ├── worker management
│   └── result aggregation
├── Orchestrator (orchestrator.py)
│   ├── task decomposition
│   ├── agent assignment
│   └── progress tracking
└── Message Bus (message_bus.py)
    ├── publish/subscribe
    ├── persistence
    └── dead letter queues
```

## Core Module Dependencies

```
src/
├── core/
│   ├── config/           # Settings hierarchy (6-layer)
│   │   ├── mode_config.py        # Per-mode .omx-config.json
│   │   └── feature_flags.py
│   ├── exceptions.py     # Structured error codes
│   ├── events.py         # Event bus system
│   ├── hook_registry/    # 48 HookPoint events
│   │   ├── enums.py
│   │   └── async_executor.py
│   ├── __init__.py
│   └── settings.py
├── llm/                  # Multi-provider abstraction
│   ├── model_manager.py  # Model aliases & caching
│   ├── message_handler.py # Role sanitization
│   └── exception_handler.py # LLM exception types
├── memory/               # Enterprise memory
│   ├── sqlite_backend.py
│   └── memory_manager.py
├── rag/                  # Retrieval-Augmented Generation
│   ├── repo_map.py       # Code understanding (from Aider)
│   ├── trigram_index.py  # Fast fuzzy search
│   └── tree_sitter_syntax.py # Syntax parsing
├── workflow/             # Execution pipeline
│   ├── pipeline_orchestrator.py # Stage execution
│   ├── mode_state.py     # Exclusive mode mutex
│   ├── ralph_ledger.py   # Progress tracking
│   └── stages/           # Pipeline stages
│       ├── ralplan_stage.py    # Consensus planning
│       ├── team_exec_stage.py  # Parallel workers
│       ├── ralph_verify_stage  # Iterative verification
│       └── precontext_intake_stage.py # Context gathering
└── tools_runtime/        # Tool execution
    ├── bash_tool.py
    ├── file_tool.py
    ├── grep_tool.py
    ├── glob_tool.py
    └── ai_comment_watcher.py
```

## Key Integrations

1. **GoalX Integration** (v2026-04-13):
   - Durable Surfaces: 9 canonical surfaces
   - Budget Guard: Resource safety monitoring
   - Worktree Isolation: Git worktree-based parallel execution
   - Integration Engine: keep_session/keep_to_source/partial_adopt
   - Intent Routing: DELIVER/EXPLORE/EVOLVE/IMPLEMENT/DEBATE

2. **Oh-My-Codex Integration** (v2026-04-14):
   - Intent Router: Keyword detection & skill auto-activation
   - Keyword Registry: 40+ skill keyword mappings
   - Mode State: Exclusive mode mutex & cross-session recovery
   - Pipeline Orchestrator: RALPLAN → team-exec → ralph pipeline
   - Session History Search: Historical session retrieval
   - Team Persistence: Team state persistence
   - Ralph Ledger: Progress ledger with visual feedback
   - Agent Prompts: 34 Agent Prompt templates
   - Agent Definitions: 40+ Agent role definitions
   - Task Analyzer: Task scale detection
   - Code Simplifier: Auto code simplification hooks

3. **Aider Integration** (v0.50.0 - 2026-04-08):
   - 18+ Aider-style commands
   - 10 edit formats (editblock, wholefile, udiff, patch)
   - 25+ model aliases with metadata caching
   - RepoMap code understanding
   - Tree-sitter syntax parsing
   - Version checking (PyPI)

<!-- Staleness: 90+ days warning: 2026-04-18 -->
