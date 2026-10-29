---
name: "hud"
description: "Show or configure the OMX HUD (two-layer statusline)"
role: "display"
scope: ".omx/**"
---

> **clawd 路径适配（重要）**：本技能移植自 oh-my-codex，文中所有 `~/.codex/...`、
> `.codex/skills/`、`CODEX_HOME` 都是 **Codex 时代的路径**。在 clawd 里真实生效的是：
>
> - 技能位置：`<项目>/skills/<name>/SKILL.md`（**支持分组子目录**，如
>   `skills/reverse/<sub>/SKILL.md`，发现逻辑是递归的）
> - 运行期数据/配置：`<项目>/.clawd/`（`sessions/`、`logs/`、`features.json` 等）
> - 查当前实际发现到的技能：`clawd hud` 或直接调 `skill` 工具；诊断环境用 `clawd doctor`
>
> 只有当你**确实在 Codex 里**运行本技能时，`~/.codex/...` 那套路径才成立。
> 在 clawd 里照着 `~/.codex/...` 找文件只会得到"不存在"。

# HUD Skill

The OMX HUD uses a two-layer architecture:

1. **Layer 1 - Codex built-in statusLine**: Real-time TUI footer showing model, git branch, and context usage. Configured via `[tui] status_line` in `~/.codex/config.toml`. Zero code required.

2. **Layer 2 - `omx hud` CLI command**: Shows OMX-specific orchestration state (ralph, ultrawork, autopilot, team, pipeline, ecomode, turns). Reads `.omx/state/` files.

## Quick Commands

| Command | Description |
|---------|-------------|
| `omx hud` | Show current HUD (modes, turns, activity) |
| `omx hud --watch` | Live-updating display (polls every 1s) |
| `omx hud --json` | Raw state output for scripting |
| `omx hud --preset=minimal` | Minimal display |
| `omx hud --preset=focused` | Default display |
| `omx hud --preset=full` | All elements |

## Presets

### minimal
```
[OMX] ralph:3/10 | turns:42
```

### focused (default)
```
[OMX] ralph:3/10 | ultrawork | team:3 workers | turns:42 | last:5s ago
```

### full
```
[OMX] ralph:3/10 | ultrawork | autopilot:execution | team:3 workers | pipeline:exec | turns:42 | last:5s ago | total-turns:156
```

## Setup

`omx setup` automatically configures both layers:
- Adds `[tui] status_line` to `~/.codex/config.toml` (Layer 1)
- Writes `.omx/hud-config.json` with default preset (Layer 2)
- Default preset is `focused`; if HUD/statusline changes do not appear, restart Codex CLI once.

## Layer 1: Codex Built-in StatusLine

Configured in `~/.codex/config.toml`:
```toml
[tui]
status_line = ["model-with-reasoning", "git-branch", "context-remaining"]
```

Available built-in items (Codex CLI v0.101.0+):
`model-name`, `model-with-reasoning`, `current-dir`, `project-root`, `git-branch`, `context-remaining`, `context-used`, `five-hour-limit`, `weekly-limit`, `codex-version`, `context-window-size`, `used-tokens`, `total-input-tokens`, `total-output-tokens`, `session-id`

## Layer 2: OMX Orchestration HUD

The `omx hud` command reads these state files:
- `.omx/state/ralph-state.json` - Ralph loop iteration
- `.omx/state/ultrawork-state.json` - Ultrawork mode
- `.omx/state/autopilot-state.json` - Autopilot phase
- `.omx/state/team-state.json` - Team workers
- `.omx/state/pipeline-state.json` - Pipeline stage
- `.omx/state/ecomode-state.json` - Ecomode active
- `.omx/state/hud-state.json` - Last activity (from notify hook)
- `.omx/metrics.json` - Turn counts

## Configuration

HUD config stored at `.omx/hud-config.json`:
```json
{
  "preset": "focused"
}
```

## Color Coding

- **Green**: Normal/healthy
- **Yellow**: Warning (ralph >70% of max)
- **Red**: Critical (ralph >90% of max)

## Troubleshooting

If the TUI statusline is not showing:
1. Ensure Codex CLI v0.101.0+ is installed
2. Run `omx setup` to configure `[tui]` section
3. Restart Codex CLI

If `omx hud` shows "No active modes":
- This is expected when no workflows are running
- Start a workflow (ralph, autopilot, etc.) and check again
