---
name: mode_state
description: 独占模式状态管理，支持互斥检查和跨会话恢复
---
## Overview
实现会话间模式状态的持久化与互斥控制，防止多个并行任务冲突，并支持在会话重启后恢复先前的模式选择。

## When to Use
- 需要限制同一时间只能执行一种特定模式（如仅允许“build”或“review”）的场景
- 需要在用户切换会话后保持上一次的模式选项，以便继续执行未完成的任务
- 在多代理协作环境中对执行模式进行统一调度

## Implementation Details
1. **状态持久化**  
   - 使用 `pickle` 或 `json` 写入/读出位于 `~/.claude/memory/mode_state.json` 的状态文件。  
   - 状态包括：`mode`（字符串标识）、`last_active`（时间戳）、`active_task_ids`（进行中的任务 ID 列表）。

2. **互斥检查**  
   - 在任何技能或代理进入 `Run` 状态前，调用 `ModeState.acquire(mode_name)` 检查当前是否已锁定。  
   - 若锁定冲突模式则抛出 `ModeConflictError`，阻止执行。  
   - `release()` 用于在任务结束时归还锁。

3. **模式恢复**  
   - 启动新会话时，读取上一次记录的 `mode`，自动将 UI 或命令行处置为该模式。  
   - 通过 `ModeState.get_active_mode()` 提供当前模式访问。

4. **线程安全**  
   - 使用文件锁 (`portalocker`) 保证并发写入安全。

5. **API 设计**  
   - `acquire(mode: str) -> bool`：尝试获取锁，成功返回 `True`。  
   - `release(mode: str)`：释放锁。  
   - `is_locked(mode: str) -> bool`：检查指定模式是否已被占用。  
   - `set_last_active(mode: str)`：记录最近活跃时间。  
   - `get_active_mode() -> str | None`：获取当前全局锁定的模式。

## Tests
- 单元测试验证互斥锁的正确获取与释放。  
- 集成测试模拟多会话情境下的模式恢复。  
- 边界测试检查并发访问时的文件锁行为。
