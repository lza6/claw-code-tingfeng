# Tool Integration Planning

## Objectives
- Consolidate tooling utilities under common patterns
- Eliminate duplication across existing functionality
- Implement best practices from oh‑my‑codex‑main

## Target Files
1. **`src/core/config.py`**
   - Add configuration options for tool behavior (feature flags, limits)
2. **`src/core/exceptions.py`**
   - Extend exception hierarchy for tool errors
3. **`src/core/replay_engine.py`**
   - Add observability hooks for tool execution
4. **`src/tools_runtime/tool_manager.py`**
   - Create central tool lifecycle manager
5. **`src/hooks/explore_routing.py`**
   - Update routing to recognize new tool patterns
6. **`README.md`**
   - Document tooling conventions and constraints

## Actions
- Reduce duplicated code modules
- Standardize error handling across tools
- Enable observability for tool usage

Proceed with modifications to the listed files to achieve integration goals.