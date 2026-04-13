# Clawd Code 架构演进与优化指南 (v1.2)

> **版本**: v1.2 (2026-04-12)
> **状态**: 执行中
> **目标**: 架构解耦、RAG 增强、自愈闭环、代码库瘦身

---

## 一、 核心改进哲学：原子化补丁引擎 (Atomic Patching)

### 1.1 现状挑战
当前系统存在多种代码修改途径：`search_replace`, `udiff`, `patch_engine` 等，逻辑重复且在处理复杂冲突时容易损坏文件。

### 1.2 优化方案
1.  **构建 `AtomicPatch` 类**：在 `src/core/patch/` 下定义最小操作集（Insert, Delete, Replace, Rename）。
2.  **格式转换器 (Format Translators)**：将 Aider 的 `editblock`, `wholefile`, `udiff` 等格式统一解析并转换为 `AtomicPatch` 序列。
3.  **安全执行器 (Safe Executor)**：在执行补丁前进行快照备份，执行后立即调用 `Tree-sitter` 进行语法校验。若失败，自动回滚并触发自愈诊断。

---

## 二、 RAG 深度演进：从文本检索到语义感知

### 2.1 增量索引 (Incremental Indexing)
- **机制**：通过 `src/rag/indexer_persistence.py` 记录文件的 `mtime` 和 `hash`。
- **效果**：仅在文件变动时重新触发 `Trigram` 和 `Tree-sitter` 解析，极大缩短冷启动时间。

### 2.2 语义块索引 (Semantic Chunking)
- **机制**：利用 `tree_sitter_syntax.py` 识别函数体、类定义和装饰器。
- **效果**：检索结果以“完整逻辑单元”返回，而非截断的文本块，提升模型理解准确度。

### 2.3 跨文件符号图 (Cross-file Symbol Graph)
- **机制**：在 `src/rag/dependency_graph.py` 中构建全局符号引用索引。
- **效果**：支持“查找调用者”、“查找定义”等高级 RAG 功能。

---

## 三、 自愈系统闭环化 (Closed-Loop Self-Healing)

### 3.1 主动验证 (Active Verification)
在 `workflow` 执行任何工具操作后，不再依赖用户手动检查，而是自动触发 `verifier.py` 进行静态扫描或运行关联测试。

### 3.2 智能诊断 (Intelligent Diagnosis)
当验证失败时，`diagnoser.py` 将结合：
1.  **Linter 输出** (来自 `linter_python.py`)。
2.  **Pytest 错误堆栈**。
3.  **代码变更 Diff**。
共同生成修复建议。

### 3.3 经验库 (Experience Bank)
成功修复的案例将存入 `sqlite_store.py`，形成“错误特征 -> 补丁模板”的映射，加速后续同类问题的解决。

### 3.4 深度反思机制 (Deep Reflection Loop)
- **机制**：将 `ReflectedMessage.from_lint` 与 `ReflectedMessage.from_test` 正式集成到 `workflow/verifier.py`。
- **流程**：当 Patch 执行后，Verifier 立即捕获 Lint/Test 错误，包装为 `ReflectedMessage` 并反馈给 LLM。如果连续 3 次失败，则触发 `SelfHealingEngine` 的“重型诊断”。

---

## 四、 代码库瘦身与大型文件拆分 (Refactoring)

### 4.1 拆分优先级 (Top 5)
1.  **`src/agent/engine.py` (763行)** → 拆分为 `engine_core.py`, `engine_session.py`, `tool_delegator.py`。
2.  **`src/server/websocket_server.py` (686行)** → 拆分为 `ws_manager.py`, `ws_protocol.py`。
3.  **`src/core/cost_estimator/cost_estimator.py` (646行)** → 拆分为 `pricing_models.py`, `token_calculators.py`。
4.  **`src/llm/structured_output.py` (643行)** → 按供应商 (OpenAI/Anthropic) 提取解析 Mixin。
5.  **`src/utils/features.py` (630行)** → 迁移至 `src/core/config/feature_flags.py`。

### 4.2 拆分原则
- **接口一致性**：通过 `__init__.py` 保持向后兼容，外部模块引用路径不变。
- **单一职责**：每个新文件不超过 400 行。

---

## 五、 清理与标准化清单

| 类别 | 目标 | 动作 |
| :--- | :--- | :--- |
| **冗余逻辑** | `diff_utils.py` | 统一合并至 `src/core/patch/` |
| **过期参数** | `deprecated_args.py` | 彻底移除，配置迁移至全局 Settings |
| **残留文件** | `*.bak`, `*.old`, `tmp/` | 建立自动化清理脚本 |
| **异常映射** | `exceptions.py` | 建立 Aider 错误码与原生异常的 1:1 映射 |

---

## 六、 验收标准 (Definition of Done)

- [ ] 所有大文件（>500行）拆分完成，单文件行数 <400。
- [ ] 测试通过率保持 100%，且关键模块覆盖率提升至 60%。
- [ ] Ruff Lint 错误数归零。
- [ ] RAG 索引支持增量更新，冷启动耗时缩短 50%。
