# 📋 Onyx → Clawd Code 整合建议清单

> 分析日期：2026-04-08  
> 项目A（主项目）：`claw-code-tingfeng` — AI编程代理框架  
> 项目B（参考项目）：`onyx-main` — 企业级AI平台（原Danswer）

---

## 一、总体对比概览

| 维度 | 项目A (Clawd Code) | 项目B (Onyx) | 差距 |
|------|-------------------|-------------|------|
| 定位 | AI编程代理（CLI/TUI为主） | 企业AI平台（Web全栈） | 不同定位，互补 |
| 语言 | Python 3.10+ | Python/TS/Go/Rust 四语言 | B更丰富 |
| LLM层 | LiteLLM单例 + 管理器 | 工厂模式 + 多租户 + 成本追踪 | **B更成熟** |
| 连接器 | 无 | 50+ 企业数据源连接器 | **B独有** |
| 工具系统 | 基础工具集（Bash/Grep/Glob） | 12类工具+沙箱执行 | **B更完善** |
| Hook系统 | 简单JSON配置 | 枚举+注册表+Spec模式 | **B更工程化** |
| Feature Flags | `utils/features.py` 简单开关 | 独立模块+DB驱动 | **B更灵活** |
| 评估系统 | 无 | Braintrust+本地双评估 | **B独有** |
| 记忆系统 | 企业LTM+SQLite | DB持久化+上下文感知 | 各有千秋 |
| 追踪系统 | OTel+Langfuse+Braintrust | OTel+Langfuse+Braintrust | 相当 |
| 测试覆盖 | 1353个测试，49%覆盖 | 多层测试+Playwright E2E | B更全面 |
| 部署方案 | Docker Compose | Docker Compose + K8s + Terraform | B更完善 |

---

## 二、整合建议清单（按优先级排序）

### 🔴 P0 — 高优先级：工具类和通用基础设施

#### 1. LLM工厂模式重构
- **现状A**: `src/llm/model_manager.py` — 单例模式 + 直接调用
- **现状B**: `onyx/llm/factory.py` — 工厂函数 + `LLMProviderView` + 多租户感知 + 成本自动追踪
- **B的优势**:
  - ✅ `get_llm()` / `get_default_llm()` / `get_llm_for_persona()` 分层工厂
  - ✅ 自动成本追踪（`_track_llm_cost`）
  - ✅ Vision模型自动检测和回退
  - ✅ 提供商特殊Header自动构建（OpenRouter排行榜、Bedrock认证）
  - ✅ 用户权限检查（`can_user_access_llm_provider`）
- **整合方案**: 在 `src/llm/` 下新增 `factory.py`，引入工厂函数模式，适配A的非多租户架构
- **影响文件**:
  - 新建 `src/llm/factory.py`
  - 修改 `src/llm/model_manager.py`（简化为工厂的薄封装）
  - 修改 `src/llm/litellm_singleton/__init__.py`（移除单例，改用工厂）

#### 2. LLM接口标准化（Provider抽象）
- **现状A**: 直接依赖LiteLLM，无中间接口层
- **现状B**: `onyx/llm/interfaces.py` — 标准 `LLM` ABC + `LLMConfig` Pydantic模型 + Braintrust `@traced` 装饰器
- **B的优势**:
  - ✅ 清晰的ABC接口（`invoke` / `stream`）
  - ✅ 统一的 `LLMConfig` 模型（所有提供商配置标准化）
  - ✅ `LLMUserIdentity` 身份追踪
  - ✅ `ReasoningEffort` 枚举（low/medium/high/auto）
  - ✅ `ToolChoiceOptions` 标准化
- **整合方案**: 在 `src/llm/` 下新增 `interfaces.py`，定义标准ABC接口
- **影响文件**:
  - 新建 `src/llm/interfaces.py`
  - 新建 `src/llm/models.py`（LLMConfig、LLMUserIdentity等Pydantic模型）
  - 修改 `src/llm/litellm_singleton/__init__.py`（实现新接口）

#### 3. 消息预处理管道（Tool Content处理）
- **现状A**: 工具调用结果直接拼接进消息
- **现状B**: `onyx/llm/multi_llm.py` — 完整的消息清洗管道
  - `_strip_tool_content_from_messages()` — 工具内容转纯文本
  - `_fix_tool_user_message_ordering()` — 修复user/assistant交替顺序
  - `_prompt_contains_tool_call_history()` — 检测工具调用历史
  - `_normalize_content()` — 统一内容序列化（字符串/list/None）
- **B的优势**: 解决Bedrock/Mistral等模型的严格消息格式要求，避免API错误
- **整合方案**: 在 `src/llm/` 下新增 `message_pipeline.py`
- **影响文件**:
  - 新建 `src/llm/message_pipeline.py`
  - 修改 `src/llm/message_sanitizer.py`（整合新的预处理逻辑）

#### 4. Hook系统升级（枚举+注册表+Spec模式）
- **现状A**: `hooks/hooks.json` — 简单JSON配置 + shell脚本
- **现状B**: `onyx/hooks/registry.py` — 枚举定义 + 注册表 + HookPointSpec抽象
- **B的优势**:
  - ✅ 类型安全的HookPoint枚举
  - ✅ 启动时校验（`validate_registry()` 检测缺失的hook）
  - ✅ 每个hook有独立的Spec类（输入/输出/执行器定义）
  - ✅ 支持测试时monkeypatch覆盖
- **整合方案**: 保留A的JSON配置（简单场景），新增Python注册表层
- **影响文件**:
  - 新建 `src/core/hooks/registry.py`
  - 新建 `src/core/hooks/specs.py`
  - 新建 `src/core/hooks/enums.py`
  - 修改 `hooks/hooks.json`（保留兼容，新增Python层）

#### 5. Feature Flags系统增强
- **现状A**: `src/utils/features.py` — 简单的环境变量检查
- **现状B**: `onyx/feature_flags/` — 独立模块 + DB驱动 + 运行时切换
- **B的优势**:
  - ✅ 功能开关可运行时修改（无需重启）
  - ✅ 支持租户级别隔离
  - ✅ 有默认值+覆盖机制
- **整合方案**: 保持A的轻量设计，但引入Feature Flag注册表模式
- **影响文件**:
  - 修改 `src/utils/features.py`（增加注册表+默认值管理）

### 🟡 P1 — 中优先级：核心能力增强

#### 6. 工具系统架构升级（工厂+注册表+接口）
- **现状A**: `src/tools_runtime/registry.py` — 简单注册表
- **现状B**: `onyx/tools/` — Tool ABC + ToolRunner + ToolConstructor工厂 + 12类实现
- **B的优势**:
  - ✅ 工具统一接口（`run()` / `get_name()` / `get_description()`）
  - ✅ ToolRunner执行器（支持超时/重试/沙箱）
  - ✅ 工具分类（搜索/代码执行/图像/KG/MCP/记忆/Web搜索/自定义）
  - ✅ Python沙箱执行（K8s/Docker两种模式）
- **整合方案**: 引入Tool ABC接口 + ToolRunner执行器，暂不引入沙箱（过重）
- **影响文件**:
  - 修改 `src/tools_runtime/base.py`（增强ABC接口）
  - 新建 `src/tools_runtime/runner.py`（ToolRunner执行器）
  - 修改 `src/tools_runtime/registry.py`（增加类型元数据）

#### 7. LLM成本追踪自动化
- **现状A**: `src/core/cost_estimator/` — 手动估算
- **现状B**: `onyx/llm/multi_llm.py` — 每次LLM调用后自动追踪成本
  - `_track_llm_cost()` 方法
  - 支持managed API key识别
  - 按租户增量存储
- **B的优势**: 无感成本追踪，自动入库
- **整合方案**: 在 `src/llm/` 中新增自动成本追踪Hook
- **影响文件**:
  - 修改 `src/llm/litellm_singleton/__init__.py`（调用后自动追踪）
  - 修改 `src/core/cost_estimator/cost_estimator.py`（增加增量更新API）
  - 修改 `src/core/token_tracker.py`（整合成本数据）

#### 8. Reasoning Model支持（推理模型适配）
- **现状A**: 无专门推理模型支持
- **现状B**: `onyx/llm/multi_llm.py` — 完整的推理模型适配
  - `model_is_reasoning_model()` 检测
  - OpenAI `reasoning` 参数（effort + summary）
  - Anthropic `thinking` 参数（budget_tokens）
  - 自动温度调整（推理模型强制temperature=1）
- **B的优势**: 自动识别o1/o3/Claude reasoning等推理模型并调整参数
- **整合方案**: 新增推理模型检测和参数适配
- **影响文件**:
  - 新建 `src/llm/reasoning_adapter.py`
  - 修改 `src/llm/reasoning.py`（整合自动检测和参数调整）

#### 9. Tokenizer统一管理
- **现状A**: `src/utils/token_counter.py` — 独立计数
- **现状B**: `onyx/llm/factory.py` — `get_llm_tokenizer_encode_func()` + NLP模块统一管理
- **B的优势**: 每个LLM实例绑定对应tokenizer，避免模型/分词器不匹配
- **整合方案**: 在LLM工厂中绑定tokenizer
- **影响文件**:
  - 修改 `src/llm/factory.py`（新增tokenizer绑定）
  - 修改 `src/utils/token_counter.py`（改为从LLM实例获取）

#### 10. 评估系统（Eval）
- **现状A**: 无
- **现状B**: `onyx/evals/` — Braintrust + 本地双评估 + CLI工具
- **B的优势**:
  - ✅ 支持多种评估提供商（Braintrust云端 / 本地）
  - ✅ CLI评估工具（`eval_cli.py`）
  - ✅ 评估结果结构化存储
- **整合方案**: 引入轻量评估框架，支持Braintrust + 本地
- **影响文件**:
  - 新建 `src/core/evals/` 目录
  - 新建 `src/core/evals/interface.py`
  - 新建 `src/core/evals/braintrust_eval.py`
  - 新建 `src/core/evals/local_eval.py`
  - 新建 `src/core/evals/cli.py`

### 🟢 P2 — 低优先级：扩展能力

#### 11. 搜索工具增强（RRF重组合 + 文档扩展）
- **现状A**: `src/tools_runtime/search_v2_tool.py` — 基础搜索
- **现状B**: `onyx/tools/tool_implementations/search/search_tool.py` — 5步搜索管道
  - 多查询生成 + RRF重组合 + LLM选择 + 文档扩展 + 结构化输出
- **B的优势**: 搜索质量显著提升（多路召回 + LLM精排）
- **整合方案**: 引入RRF重组合 + LLM文档选择（简化版5步管道）
- **影响文件**:
  - 修改 `src/tools_runtime/search_v2_tool.py`（增加RRF和LLM选择）

#### 12. Provider特殊Header处理
- **现状A**: 统一header格式
- **现状B**: `onyx/llm/factory.py` — `_build_provider_extra_headers()` 针对不同提供商构建特殊Header
  - OpenRouter: `HTTP-Referer` + `X-Title`（排行榜追踪）
  - Bedrock: Bearer Token认证
  - Vertex AI: 凭证文件路径
- **整合方案**: 增加提供商Header适配器
- **影响文件**:
  - 修改 `src/llm/factory.py`（新增header构建逻辑）

#### 13. 模型输出格式控制（Structured Output）
- **现状A**: `src/llm/structured_output.py` — 基础支持
- **现状B**: 通过 `response_format` + `structured_response_format` 参数传递，支持JSON Schema约束
- **B的优势**: 与LLM调用无缝集成
- **整合方案**: 整合到标准LLM调用流程
- **影响文件**:
  - 修改 `src/llm/interfaces.py`（确保invoke/stream支持structured_response_format）

---

## 三、B项目独有但A可借鉴的扩展点

| 扩展点 | B的实现 | A的可借鉴价值 | 整合难度 |
|--------|---------|-------------|---------|
| **50+数据连接器** | `onyx/connectors/` 工厂+注册表+50个实现 | A无数据源集成需求，暂不需要 | ⛔ 不需要 |
| **代码沙箱执行** | K8s Pod + Docker-in-Docker | A是CLI工具，沙箱过重 | ⛔ 不需要 |
| **多租户支持** | 租户隔离DB + 独立迁移 | A是单用户CLI，不需要 | ⛔ 不需要 |
| **联邦连接器** | 不拉取数据，远端检索 | A不需要 | ⛔ 不需要 |
| **深度研究** | `onyx/deep_research/` 多步研究循环 | ⭐ 可整合到A的swarm系统 | 🟡 中 |
| **知识图谱** | `onyx/kg/` Vespa+聚类+实体提取 | A的brain/world_model可借鉴 | 🟡 中 |
| **语音多提供商** | Azure/OpenAI/ElevenLabs | A只有单一voice工具 | 🟢 低 |
| **图像生成多提供商** | OpenAI/Azure/Vertex | A无图像生成 | 🟢 低 |
| **Widget嵌入式组件** | Vite+TS独立组件 | A是CLI，不需要 | ⛔ 不需要 |
| **Tauri桌面应用** | Rust+WebView | A是CLI，不需要 | ⛔ 不需要 |
| **Chrome浏览器扩展** | 浏览器集成 | A不需要 | ⛔ 不需要 |
| **MCP Server** | `onyx/mcp_server/` 完整实现 | A有MCP但较简单 | 🟡 中 |

---

## 四、不建议整合的部分

| B的部分 | 原因 |
|---------|------|
| 多租户架构 | A是单用户CLI工具，架构不匹配 |
| 50+数据连接器 | A定位是编程代理，不需要企业数据源集成 |
| SAML/SCIM/OIDC企业认证 | A不需要企业级认证 |
| Stripe计费 | A是开源项目，无商业计费需求 |
| K8s沙箱执行 | 对CLI工具来说过于复杂 |
| Vespa文档索引引擎 | A使用Trigram+Tree-sitter已足够 |
| Next.js前端 | A是CLI/TUI，架构不同 |

---

## 五、整合执行计划

### 第一阶段（P0 — 基础设施）
1. ✅ 新建 `src/llm/factory.py` — LLM工厂
2. ✅ 新建 `src/llm/interfaces.py` — LLM标准接口
3. ✅ 新建 `src/llm/models.py` — LLM Pydantic模型
4. ✅ 新建 `src/llm/message_pipeline.py` — 消息预处理管道
5. ✅ 新建 `src/core/hooks/registry.py` — Hook注册表
6. ✅ 修改 `src/utils/features.py` — Feature Flag增强

### 第二阶段（P1 — 核心能力）
7. ✅ 修改 `src/tools_runtime/base.py` — 工具ABC增强
8. ✅ 新建 `src/tools_runtime/runner.py` — ToolRunner
9. ✅ 新建 `src/llm/reasoning_adapter.py` — 推理模型适配
10. ✅ 修改成本追踪 — 自动记录
11. ✅ 新建 `src/core/evals/` — 评估系统

### 第三阶段（P2 — 扩展能力）
12. ✅ 搜索工具增强（RRF + LLM选择）
13. ✅ MCP Server增强
14. ✅ 语音/图像生成多提供商

---

## 六、风险提示

| 风险 | 缓解措施 |
|------|---------|
| 工厂模式引入后现有代码需适配 | 保持向后兼容，旧接口标记deprecated |
| Hook注册表改动可能破坏现有hooks | 保留JSON配置的兼容层 |
| LLM接口变更影响所有调用点 | 通过测试套件验证（1353个测试） |
| 成本追踪增加DB写入 | 异步批处理，不阻塞主流程 |

---

*本文档由 AI 架构师自动生成，建议人工审查后执行。*
