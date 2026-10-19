# AGENTS.md

> **执行契约与记忆**：动手前先读 `.agent/rules.md`、`.agent/memory/*.md`，
> 并按任务匹配 `.agent/skills/*.md`。计划文档审计见 `reports/plan-audit-2026-10-19.md`，
> 变更报告与测验见 `reports/change-report-2026-10-19.html`。

This file provides guidance to AI coding agents when working with code in this repository.

## Repository Overview

Clawd Code is an AI-powered coding agent framework (Python 3.10+) featuring multi-agent swarm intelligence, self-healing, codebase awareness, enterprise-grade RAG, and a full workflow engine.

## Architecture

### Multi-Agent Swarm System

The swarm system in `src/agent/swarm/` orchestrates specialized agents:

| Role | File | Responsibility |
|------|------|---------------|
| **Orchestrator** | `orchestrator.py` | Task decomposition and dispatch |
| **Coder/Worker** | `coder_agent.py` | Code implementation |
| **Architect** | `architect_agent.py` | Architecture design and review |
| **Auditor** | `auditor.py` | Code audit and quality checks |
| **Integrator** | `integrator.py` | Result integration |

### Self-Fission System

`src/agent/swarm/self_fission/` automatically splits complex tasks into sub-tasks:

| Detector | File | Triggers On |
|----------|------|-------------|
| Security | `detectors/security.py` | Security-sensitive code patterns |
| Performance | `detectors/performance.py` | Performance-critical operations |
| SQL | `detectors/sql_usage.py` | Database query patterns |
| CSS/TUI | `detectors/css_tui.py` | Styling and terminal UI |
| Crypto | `detectors/crypto.py` | Cryptographic operations |
| Documentation | `detectors/doc_needs.py` | Documentation gaps |

### Agent Personas (Prompt Templates)

Located in `agents/`, these are prompt-based personas that can be used to configure agent behavior:

- **code-reviewer.md** — For code review tasks (five-axis evaluation)
- **security-auditor.md** — For security-focused reviews
- **test-engineer.md** — For test strategy and quality assurance

### World Model (Brain)

`src/brain/world_model.py` — The system's "consciousness layer":
- Maintains a live dependency graph of the codebase (AST-based)
- Trigram-based semantic index for code search
- Pattern detection (Factory, Strategy, Observer, Singleton, etc.)
- Intent caching for efficient repeated queries

### Self-Healing Engine

`src/self_healing/engine.py` — Autonomous error recovery:
1. Error classification (classifier.py)
2. AI-driven diagnosis (diagnoser.py)
3. Fix generation and application
4. Verification (verifier.py)
5. Experience storage for future reference

## Creating New Code

### File Structure

```
src/
  <module>/
    __init__.py          # Public API exports
    <feature>.py         # Implementation
tests/
  <module>/
    test_<feature>.py    # Mirror source structure
```

### Testing Standards

- Use pytest with descriptive test names
- Follow Arrange-Act-Assert pattern
- Mock at system boundaries (LLM calls, file I/O, network)
- Each test should verify one concept
- Tests must be independent (no shared mutable state)

### Error Handling

Use structured error codes from `src/core/exceptions.py`:

```python
from src.core.exceptions import ClawdError, ErrorCode

raise ClawdError(ErrorCode.CONFIG_MISSING, "API key not configured")
```

### Settings

Access settings via the 6-layer config system:

```python
from src.core.settings import AgentSettings

settings = AgentSettings()
model = settings.llm_model
```

## Code Quality Gates

Before submitting changes:

1. `python -m pytest tests/ -v --tb=short` — All tests pass
2. `ruff check src/` — No lint errors
3. No secrets or API keys in code
4. Error handling uses structured error codes
5. New dependencies added to both `requirements.txt` and `pyproject.toml`

## Creating New Skills

### Directory Structure

```
skills/
  {skill-name}/           # kebab-case directory name
    SKILL.md              # Required: skill definition
    scripts/              # Optional: executable scripts
      {script-name}.sh    # Bash scripts (preferred)
```

### Naming Conventions

- **Skill directory**: `kebab-case` (e.g. `web-quality`)
- **SKILL.md**: Always uppercase, always this exact filename
- **Scripts**: `kebab-case.sh` (e.g., `deploy.sh`, `fetch-logs.sh`)

### SKILL.md Format

```markdown
---
name: {skill-name}
description: Brief statement of what the skill does. Use when [specific trigger conditions].
---

# {Skill Title}

{Brief description of what the skill does.}
```

See [docs/skill-anatomy.md](docs/skill-anatomy.md) for the full specification.

### Best Practices for Context Efficiency

Skills are loaded on-demand — only the skill name and description are loaded at startup. The full `SKILL.md` loads into context only when the agent decides the skill is relevant. To minimize context usage:

- **Keep SKILL.md under 500 lines** — put detailed reference material in separate files
- **Write specific descriptions** — helps the agent know exactly when to activate the skill
- **Use progressive disclosure** — reference supporting files that get read only when needed
- **Prefer scripts over inline code** — script execution doesn't consume context (only output does)
- **File references work one level deep** — link directly from SKILL.md to supporting files

### Script Requirements

- Use `#!/bin/bash` shebang
- Use `set -e` for fail-fast behavior
- Write status messages to stderr: `echo "Message" >&2`
- Write machine-readable output (JSON) to stdout
- Include a cleanup trap for temp files

### What Not to Do

- Don't duplicate content between skills — reference other skills instead
- Don't add skills that are vague advice instead of actionable processes
- Don't create supporting files unless content exceeds 100 lines
- Don't put reference material inside skill directories — use `references/` instead

### Packaging and Distribution

Skills can be packaged for distribution:

```bash
cd skills
zip -r {skill-name}.zip {skill-name}/
```

**Installation methods:**

- **Claude Code:** `cp -r skills/{skill-name} ~/.claude/skills/`
- **claude.ai:** Add the skill to project knowledge or paste SKILL.md contents into the conversation

If a skill requires network access, instruct users to add required domains at `claude.ai/settings/capabilities`.

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->
