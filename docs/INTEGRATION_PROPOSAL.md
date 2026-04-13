# 整合建议清单

## 实施状态总览

| 阶段 | 内容 | 状态 | 完成时间 |
|------|------|------|----------|
| Phase 1 | 核心编辑策略 | ✅ 已完成 | 2026-04-08 |
| Phase 2 | 提示词工程 | ✅ 已完成 | 2026-04-08 |
| Phase 3 | Git 功能增强 | ✅ 已完成 | 2026-04-08 |
| Phase 4 | 历史压缩 | ✅ 已完成 | 2026-04-08 |
| Phase 5 | 双模型协作 | ⏳ 待实施 | - |
| Phase 6 | Reasoning 支持 | ⏳ 待实施 | - |

---

## 项目对比

| 维度 | Claw-Code-Tingfeng (A) | Aider (B) |
|------|------------------------|-----------|
| **架构模式** | 多 Agent 协作 + Self-Fission | 单 Agent 多 Coder 策略 |
| **代码编辑** | ~~无统一编辑策略~~ → **已有 code_edit 模块** | EditBlock/Udiff/Wholefile 多策略 |
| **Git 集成** | 基础实现 → **已增强 undo/diff** | 成熟的 undo/diff/归因 |
| **提示词工程** | ~~分散在各模块~~ → **已有 prompts 模块** | 集中的 Prompts 类 + 示例对话 |
| **错误恢复** | Self-Healing 系统 | 多级匹配回退策略 |
| **上下文感知** | World Model + Repomap | Repomap (PageRank) |
| **记忆系统** | 三层记忆 + 细粒度分类 | 无 |
| **工作流** | 五阶段管道 | 无 |

---

## 已完成的整合

### ✅ 第一阶段：核心编辑策略

#### 1.1 创建 `src/tools_runtime/code_edit/` 模块
**状态**: ✅ 已完成

**新建文件**:
- `src/tools_runtime/code_edit/__init__.py` - 工厂入口
- `src/tools_runtime/code_edit/base_coder.py` - 基类 (EditResult, MatchType)
- `src/tools_runtime/code_edit/editblock_coder.py` - SEARCH/REPLACE 块编辑
- `src/tools_runtime/code_edit/fuzzy_matcher.py` - 模糊匹配引擎

**测试结果**:
```
[OK] code_edit module imported
[OK] Created coder: EditBlockCoder
[OK] Exact match: success=True, match_type=exact
[OK] Fuzzy match: success=True, match_type=fuzzy
```

#### 1.2 移植多级匹配策略
**状态**: ✅ 已完成

**已实现的匹配策略**:
1. `perfect_replace()` - 精确匹配
2. `replace_part_with_missing_leading_whitespace()` - 空白容错
3. `try_dotdotdots()` - `...` 省略语法
4. `replace_closest_edit_distance()` - 编辑距离模糊匹配

---

### ✅ 第二阶段：提示词工程增强

#### 2.1 创建集中式提示词管理
**状态**: ✅ 已完成

**新建文件**:
- `src/llm/prompts/__init__.py` - 模块入口
- `src/llm/prompts/base_prompts.py` - 基础提示词类 (PromptSection, CODING_PRINCIPLES)
- `src/llm/prompts/edit_prompts.py` - 编辑相关提示词 (8个示例对话)

**测试结果**:
```
[OK] EditPrompts created
[OK] System message length: 1892 chars
[OK] Example messages: 8
[OK] Factory: EditPrompts
```

#### 2.2 添加示例对话 (Few-shot Learning)
**状态**: ✅ 已完成

**已添加的示例**:
- 修改函数内容
- 创建新文件
- 删除代码
- 添加错误处理

---

### ✅ 第三阶段：Git 功能增强

#### 3.1 增强 undo 安全性
**状态**: ✅ 已完成

**修改文件**: `src/core/git_integration.py`

**新增功能**:
- `commit_with_attribution()` - 多层归属控制
- `undo_multiple_commits()` - 多级回退
- `get_aider_commits()` - 获取本会话 AI commits
- `can_undo()` - 检查是否可执行 undo

#### 3.2 添加 diff 命令增强
**状态**: ✅ 已完成 (之前已有实现)

---

### ✅ 第四阶段：历史压缩

#### 4.1 创建历史压缩模块
**状态**: ✅ 已完成

**新建文件**: `src/agent/history_compressor.py`

**已实现功能**:
- `HistoryCompressor` 类 - 递归压缩
- `CompressionResult` 数据类
- `create_simple_token_counter()` - 简单 token 计数器
- `SUMMARIZE_PROMPT` / `SUMMARY_PREFIX` - 压缩提示词

**测试结果**:
```
[OK] Token counter created
[OK] HistoryCompressor created
[OK] Estimated tokens saved: 63
```

---

## 待实施的整合

### ⏳ 第五阶段：双模型协作 (低优先级)

#### 5.1 Architect 模式
**借鉴**: Aider 的 `architect_coder.py`
**改进**: `src/agent/modes/architect.py`

**设计**:
- Architect 生成修改方案描述
- Editor 根据描述执行修改
- 支持多轮迭代

---

### ⏳ 第六阶段：Reasoning 支持 (低优先级)

#### 6.1 支持 DeepSeek R1 等推理模型
**借鉴**: Aider 的 `reasoning_tags.py`
**文件**: `src/llm/reasoning_handler.py` - 新建

**功能**:
- 解析 `<tool_call>` 等推理标签
- 自动剥离 reasoning 内容后再应用编辑

---

## 不整合的内容 (A 优于 B)

| 功能 | 原因 |
|------|------|
| 记忆系统 | A 的三层记忆架构更完善 |
| Self-Healing | A 的经验库 + AI 诊断更健壮 |
| 多 Agent 协作 | A 的 Swarm + Self-Fission 是核心优势 |
| 工作流引擎 | A 的五阶段管道更适合企业场景 |
| RAG 系统 | A 的 BM25 + Trigram 更轻量 |

---

## 文件变更清单

### 已新建文件 (7个) ✅
```
src/tools_runtime/code_edit/__init__.py    ✅
src/tools_runtime/code_edit/base_coder.py  ✅
src/tools_runtime/code_edit/editblock_coder.py ✅
src/tools_runtime/code_edit/fuzzy_matcher.py ✅
src/llm/prompts/__init__.py               ✅
src/llm/prompts/base_prompts.py           ✅
src/llm/prompts/edit_prompts.py           ✅
src/agent/history_compressor.py           ✅
```

### 已修改文件 (3个) ✅
```
src/core/git_integration.py - 增强 undo/diff ✅
src/llm/__init__.py - 导出 prompts 模块 ✅
src/tools_runtime/__init__.py - 导出 code_edit 模块 ✅
```

### 待新建文件 (可选)
```
src/tools_runtime/code_edit/udiff_coder.py - Unified Diff 编辑器
src/tools_runtime/code_edit/wholefile_coder.py - 整文件替换
src/llm/prompts/architect_prompts.py - 架构师模式提示词
src/llm/reasoning_handler.py - Reasoning 支持
```

---

## 预期收益

| 收益 | 说明 |
|------|------|
| **编辑成功率提升** | 多级匹配策略可处理 LLM 输出的格式偏差 ✅ |
| **提示词可维护性** | 集中式管理 + 示例对话，便于迭代优化 ✅ |
| **Git 安全性增强** | 更健壮的 undo 和归因机制 ✅ |
| **上下文效率** | 历史压缩减少 token 消耗 ✅ |
| **架构清晰** | 策略模式解耦编辑逻辑 ✅ |
