# Clawd Code Architecture

<!-- Generated: 2026-04-18 | Files scanned: 695 | Token estimate: ~600 -->

## System Overview

**Project type**: Python AI Agent Framework (single app + library)
**Entry point**: `src/main.py`
**Version**: 0.45.0

## Core Modules

```
src/
├── main.py          # CLI entry point,argparse, delayed imports
├── agent/          # Agent engine,swarm orchestration
├── brain/          # World Model,codebase awareness
├── cli/            # REPL interface,TUI
├── core/           # Settings,events,exceptions,hooks
├── llm/            # Multi-provider LLM abstraction
├── memory/         # Enterprise long-term memory
├── rag/            # Trigram index, repo map, syntax parsing
├── self_healing/   # Auto error detection,AI-driven repair
├── tools_runtime/  # Tool execution (bash,file,grep,glob)
├── workflow/       # 5-phase execution pipeline
└── utils/          # Shared utilities (from Aider)
```

## Key Dependencies

- **LLM Providers**: OpenAI, Anthropic, Google, Cohere, HuggingFace, Ollama, Together, Azure, OpenRouter
- **Database**: SQLite (memory), async I/O
- **Parsing**: tree-sitter (syntax), grep_ast (code search)
- **CLI**: prompt-toolkit (TUI), readline

## Workflow Pipeline

```
Pipeline Orchestrator (pipeline_orchestrator.py)
├── RalplanStage     → Planner→Architect→Critic consensus
├── TeamExecStage  → Parallel workers (Git worktree isolation)
└── RalphVerifyStage → Iteration until verified
```

## Event System

38 NotificationEvent types covering:
- Session lifecycle
- Agent lifecycle
- Task/workflow
- Pipeline stages
- Team collaboration
- Self-healing
- Budget/resource monitoring

## Hook System

48 HookPoint events for extensibility:
- PreToolUse/PostToolUse
- Pipeline stage hooks
- Session lifecycle hooks
- Error detection hooks

<!-- Staleness: 90+ days warning: 2026-04-18 -->