# Change Index（v0.60.0 → v0.60.2）

## 入口与配置
- `src/cli/entrypoint.py`：新增 `clawd server` 命令，打印实际监听端口。
- `src/cli/repl_commands.py`：doctor 增加能力状态（RAG/World Model/Server）。
- `pyproject.toml`：版本 0.60.2；`dev` 补 ruff/pytest-cov；新增 `tracing` extras；pytest 禁用无关插件。
- `.github/workflows/ci.yml`：lint 分层；移除非法参数；覆盖率阈值 45。

## Agent / LLM
- `src/llm/config.py`：`LLMMessage` 支持 tool_calls/tool_call_id/name；`LLMResponse.tool_calls`。
- `src/llm/providers/openai.py`：原生 tool_calls 解析与消息序列化。
- `src/agent/engine_loop.py`：原生调用优先；id 按调用顺序；失败/过滤调用补 tool 消息；流式回退。
- `src/agent/engine.py`：`_build_tool_schemas`；SkillTool 注册；RAG/流式告警。
- `src/agent/factory.py`：`CLAWD_ENABLE_RAG` 接线。
- `src/agent/_system_prompt.py`：Skill 摘要注入。
- `src/agent/skill_loader.py`、`src/tools_runtime/skill_tool.py`：新增。
- `src/agent/tool_manager.py`、`src/tools_runtime/base.py` 及各工具：`risk_kind`。

## 持久化 / 工作流
- `src/utils/file_ops.py`：`file_lock`（可重入 + owner + 原子回收）、原子写重试。
- `src/workflow/pipeline_orchestrator.py`：schema/attempt/working_path/expected_attempt；artifacts 归一化。
- `src/workflow/mode_state.py`：update_state/cancel_mode 读改写加锁。
- `src/workflow/team_persistence.py`：`_mutate_team_state` 读改写加锁。
- `src/workflow/ralph_ledger.py`：add_progress_entry 读改写加锁。
- `src/workflow/stages|pipeline_stages/__init__.py`：标注为非生产平行实现。

## 安全 / 可观测
- `src/tools_runtime/scrape_tool.py`：SSRF 校验、重定向前置拦截、模块级 `SafeRedirectHandler`。
- `src/core/tracing/setup.py` + `src/main.py`：tracing 返回 bool、接线、逐 provider 隔离。
- `src/__init__.py`：版本解析 pyproject 优先。

## 测试
- 新增：`test_state_persistence_semantics.py`(14)、`test_tool_policy.py`(10)、`test_scrape_ssrf.py`(25)、`test_skill_injection.py`(6)、`test_native_tool_calls.py`(9)、`test_server_port_semantics.py`(3)、`test_state_persistence_windows_safe.py`(2)。
- 修复：tests 中 4 个 F811。
- 默认跳过：`test_goalx_integration.py`（真实 LLM，`RUN_GOALX_E2E=1` 启用）。
- 删除：`tests/test_slop_data.py`（无测试函数）。

## v0.60.4 补充
- `src/core/state_impl.py`：`save_snapshot` 改用 `file_lock + atomic_write`（原 `import fcntl` 在 Windows 必失败）。
- `src/core/state/persistence.py`：快照/事件原子写；`append_event` 读改写加锁。
- 收集基线：3167 tests / 0 errors / 78.99s。
