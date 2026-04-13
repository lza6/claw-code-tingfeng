# Clawd Code 重构蓝图 (Refactoring Blueprints)

本指南为大型文件的拆分提供具体的函数搬迁路径，确保代码整洁且接口兼容。

## 1. `src/agent/engine.py` (763行) 拆分方案

### 目标结构
- `engine.py` (保持接口导出，作为 Facade)
- `engine_lifecycle.py` (初始化、运行循环、关闭)
- `engine_tools.py` (工具解析、并行执行、RAG 补丁)
- `engine_metrics.py` (Token 计数、成本报告、性能指标)
- `engine_events.py` (所有 `publish_*` 方法)

### 搬迁详情
| 目标文件 | 搬迁函数/类 |
| :--- | :--- |
| **engine_lifecycle.py** | `AgentEngine` 核心类, `__init__`, `run`, `run_stream`, `graceful_shutdown` |
| **engine_tools.py** | `_execute_tool`, `_execute_tools_parallel`, `_parse_tool_calls`, `_deep_rag_patch`, `add_tool`, `remove_tool` |
| **engine_metrics.py** | `_count_tokens`, `get_cost_report`, `get_perf_metrics`, `get_failover_report` |
| **engine_events.py** | `publish_task_started`, `publish_llm_call_completed`, `publish_token_and_cost_update` 等所有事件方法 |

---

## 2. `src/server/websocket_server.py` (686行) 拆分方案

### 目标结构
- `ws_manager.py` (连接管理、心跳、认证)
- `ws_router.py` (消息路由、协议分发)
- `ws_models.py` (Request/Response Pydantic 模型)

---

## 3. 原子补丁引擎 (`Atomic Patch Engine`) 设计

### 数据结构 (`src/core/patch/models.py`)
```python
class PatchOperation(Enum):
    INSERT = "insert"
    DELETE = "delete"
    REPLACE = "replace"

class AtomicChange(BaseModel):
    op: PatchOperation
    path: Path
    line_start: int
    line_end: int
    content: str
    checksum: str # 确保修改前的行内容匹配
```

### 执行流
1. **Parse**: `EditParser` 将文本转换成 `list[AtomicChange]`。
2. **Validate**: 检查目标文件的 `checksum`。
3. **Apply**: 内存中修改文件内容。
4. **Verify**: 调用 `Tree-sitter` 检查语法错误。
5. **Flush**: 写入磁盘。

---

## 4. RAG 增量索引方案

### 实现路径：`src/rag/incremental_indexer.py`
1. **状态存储**：使用 SQLite 或 JSON 记录 `{file_path: (mtime, hash)}`。
2. **差分扫描**：启动时仅扫描 `mtime > last_scan_time` 的文件。
3. **清理逻辑**：如果文件已删除，从 `TrigramIndex` 中移除对应的 ID。
