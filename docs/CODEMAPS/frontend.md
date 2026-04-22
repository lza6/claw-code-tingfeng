# Frontend Architecture

<!-- Generated: 2026-04-18 | Files scanned: 695 | Token estimate: ~500 -->

## UI Structure

**Framework**: No dedicated frontend framework; TUI-based CLI interface
**UI Modules**:
- `src/cli/` - REPL interface components
- `src/screens/` - Screen definitions
- `src/utils/` - Display utilities

## CLI/TUI Components

```
src/cli/
├── entrypoint.py        # CLI bootstrap
├── completer.py         # Auto-completion
├── display.py           # Output formatting
├── lexer.py             # Syntax highlighting
├── prompt.py            # Prompt rendering
├── repl_engine.py       # REPL loop
└── tui_components.py    # TUI widgets

src/screens/
├── agent_output.py      # Agent response display
├── cost_report.py       # Cost tracking UI
└── status_bar.py        # Status indicators
```

## State Management

Simplified: `src/cli/repl_engine.py` - in-memory conversation state

## Key Design Notes

- Primarily text-based interaction
- No web frontend components
- User experience focused on terminal rendering

<!-- Staleness: 90+ days warning: 2026-04-18 -->