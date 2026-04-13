# GoalX Configuration

GoalX works with zero config. Use configuration only when you need explicit control.

## Config Locations

- user-level: `~/.goalx/config.yaml`
- project-level: `.goalx/config.yaml`

## Typical Example

User-level selection policy in `~/.goalx/config.yaml`:

```yaml
selection:
  disabled_engines:
    - aider

  disabled_targets:
    - claude-code/sonnet

  master_candidates:
    - codex/gpt-5.4
    - claude-code/opus

  worker_candidates:
    - codex/gpt-5.4
    - claude-code/opus
    - codex/gpt-5.4-mini

  master_effort: high
  worker_effort: medium
```

Project-level shared config in `.goalx/config.yaml`:

```yaml
master:
  check_interval: 2m

preferences:
  worker:
    guidance: "Bias toward small, mergeable implementation slices."
  simple:
    guidance: "Use the fast path for lightweight work."

local_validation:
  command: "go build ./... && go test ./... && go vet ./..."
```

## Principles

- Keep one resolver path. Do not invent alternate config entrypoints.
- Use overrides only when they clearly improve execution.
- Explicit `--engine/--model` is an override, not the default path.
- Unknown config should fail loudly, not degrade silently.
- `selection` is only supported in `~/.goalx/config.yaml`.

## What Config Is For

- defining long-term candidate pools and disabled engines/targets
- pinning shared validation, context, and check intervals
- setting local validation

## What Config Is Not For

- encoding orchestration judgment in the framework
- replacing the normal `goalx run "goal"` path
- hand-editing live run state

## Legacy Compatibility

Older config keys such as `preset`, `master`, `roles`, `routing`, and `preferences` still load for backward compatibility.
They are not the recommended public control surface, and the normal CLI no longer exposes `--preset` or `--route-*` flags.

The recommended default path is:

- user-level `selection.*` for engine/model candidate pools
- project-level `.goalx/config.yaml` for shared repo facts such as validation, context, and check interval
- use `master_candidates` / `worker_candidates` and `master_effort` / `worker_effort`, not the removed `research_*` / `develop_*` keys
