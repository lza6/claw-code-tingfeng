# Dependencies

<!-- Generated: 2026-04-18 | Files scanned: 695 | Token estimate: ~500 -->

## External Services

| Service | Purpose | Integration |
|---------|---------|-------------|
| **OpenAI** | LLM provider | Primary model source (GPT-4, etc.) |
| **Anthropic** | LLM provider | Claude API integration |
| **Google** | LLM provider | Gemini models |
| **OpenRouter** | LLM aggregator | Multi-provider routing |
| **Cohere** | LLM provider | Command models |
| **HuggingFace** | LLM provider | Inference API |
| **Ollama** | Local LLM | Self-hosted models |
| **Together** | LLM provider | Open source models |
| **Azure OpenAI** | LLM provider | Enterprise hosting |
| **Stripe** | Billing | Payment processing (optional) |
| **GitHub** | VCS integration | Repo operations, PRs |
| **Discord/Slack/Telegram** | Notifications | Multi-platform alerts |

## Python Dependencies

**Core** (from pyproject.toml):
```
pydantic          # Data validation
pydantic-settings # Config management
rich              # Terminal formatting
prompt-toolkit    # TUI framework
diskcache         # Persistent cache
networkx          # DAG operations
tree-sitter       # Syntax parsing
pathspec          # .gitignore patterns
httpx             # Async HTTP
aiofiles          # Async file I/O
```

**LLM Providers**:
```
openai            # OpenAI API
anthropic         # Claude API
google-generativeai # Gemini
cohere            # Cohere API
huggingface-hub   # HF inference
```

**Development**:
```
pytest            # Testing framework (50% coverage target)
pytest-cov        # Coverage reporting
ruff              # Linting & formatting
mypy              # Type checking
black             # Code formatting
```

## File System Dependencies

```
src/utils/
├── file_patterns.py    # .gitignore pattern matching
├── diff_utils.py       # Unified diff generation
├── urls.py             # Documentation URLs
└── report.py           # Bug reporting

src/tools_runtime/
├── bash_tool.py        # Shell command execution
├── file_tool.py        # File operations
├── grep_tool.py        # Code search
└── glob_tool.py        # Pattern matching
```

## Integration Points

1. **Git** - Native via subprocess (git worktree, commit, diff)
2. **PyPI** - Version checking, package updates
3. **Shell** - Command execution (platform-specific)
4. **Environment** - `.env` loading via `python-dotenv`

<!-- Staleness: 90+ days warning: 2026-04-18 -->