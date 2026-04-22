# Data Architecture

<!-- Generated: 2026-04-18 | Files scanned: 695 | Token estimate: ~600 -->

## Storage Systems

**Primary**: SQLite (file-based)
**Cache**: Diskcache (optional, for RAG)
**Memory**: In-process dictionaries

## Database Schema

### SQLite Tables (memory/)

```
src/memory/sqlite_backend.py
├── sessions          # Chat session history
├── messages          # Individual messages
├── memories          # Long-term memory entries
└── embeddings        # Vector storage (optional)
```

### State Files (`.clawd/`)

```
~/.clawd/
├── session_store.json       # Session persistence
├── worktree_state.json      # Git worktree isolation state
├── pipeline/                # Pipeline execution state
│   ├── autopilot.json
│   └── {pipeline}.json
├── feature_flags.json       # Runtime feature flags
├── hooks/                   # Plugin hooks
└── config/                  # Mode configuration
    ├── .omx-modes.json      # Global mode config
    └── .omx-mode-{mode}.json # Per-mode configs
```

## Data Flow

```
User Input
    ↓
Session Store (session_store.json)
    ↓
Message History (in-memory + persisted)
    ↓
Memory Manager (embedding store)
    ↓
LLM Provider (external)
    ↓
Response → Session Store
```

## Key Data Structures

```python
# Agent communication (message_bus.py)
AgentMessage:
  sender: str
  recipient: str
  message_type: MessageType
  content: str
  metadata: dict
  correlation_id: str

# Pipeline stage (types.py)
StageResult:
  status: StageStatus (SUCCESS|FAILED|SKIPPED)
  artifacts: dict
  duration_ms: int
  error: str | None

# Workflow state (mode_state.py)
ModeState:
  mode: str
  active: bool
  current_phase: str
  metadata: dict
```

<!-- Staleness: 90+ days warning: 2026-04-18 -->