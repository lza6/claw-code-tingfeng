# 超级智能体增强模块 — 使用与运维指南

> 本文档与代码真实状态同步（2026-10-27 收口）。所有示例命令均实际验证过。

## 一、这套增强是什么

在 clawd 原有能力之上新增 5 大能力块：

| 能力 | 模块 | 一句话说明 |
|------|------|-----------|
| MCP 桥接 | `src/mcp/client.py` `tool_bridge.py` | 接入任意外部 MCP server（GhidraMCP、x64dbg 等），工具与自研工具无差别调用 |
| 反推推理 | `src/reasoning/patterns.py` | 4 种推理循环：reflexion / plan-execute / lats / debate |
| 逆向工具 | `src/reverse_tools/` | Ghidra HTTP 桥、strings/熵/hexdump、objdump/binwalk 等包装 |
| 安全治理 | `src/mcp/governance.py` `src/security/catalog.py` | 工具签名+检疫审批防投毒；安全工具 scope 授权门禁 |
| 上下文工程 | `src/reasoning/context_engineering.py` | 长会话观察截断 + 历史压缩 |

## 二、快速开始

### 2.1 推理模式 CLI（已接入 Typer 入口）

```bash
# 反思修正循环（逆向分析默认选择）
venv/Scripts/python.exe -m src reason reflexion "分析 0x401000 处函数的算法"

# 多分支假设树
venv/Scripts/python.exe -m src reason lats "识别该二进制的混淆方案" --branching 4 --depth 3

# 对抗审查一个结论（防误报）
venv/Scripts/python.exe -m src reason debate "审查: 这是登录函数" --conclusion "这是登录函数"

# JSON 全量输出（供脚本消费）
venv/Scripts/python.exe -m src reason plan-execute "全链路分析 sample.exe" --json
```

> ⚠️ 推理模式需要配置 LLM API Key（走 litellm）。无 Key 时启动会报"LLM 适配失败"。

### 2.2 外部 MCP server 接入（三步）

**第 1 步**：写配置 `.clawd/mcp_servers.json`：

```json
{
  "servers": [
    {"name": "ghidra", "transport": "http", "url": "http://localhost:8080/mcp", "timeout_seconds": 60},
    {"name": "analyzer", "transport": "stdio", "command": "python", "args": ["-m", "some_mcp_server"]}
  ]
}
```

**第 2 步**：治理放行（新 server 默认检疫期，不放行不桥接）：

```python
from src.mcp.governance import ToolGovernor
g = ToolGovernor()          # 状态存 .clawd/mcp_governance.json
g.approve("ghidra", "安全审查通过")   # 拒绝用 g.reject("name", "原因")
```

**第 3 步**：启动 agent 会话，工具自动装配。效果：
- 逆向工具（ghidra/strings/entropy/hexdump/objdump/binwalk 等 8 个）始终自动装配
- 已放行的 MCP server 工具以 `mcp__<server>__<tool>` 命名进入 agent 工具池
- 检疫期/被拒 server **自动跳过**（日志可见），不影响启动

**安全机制**：已放行 server 的工具描述或参数 schema 发生变更 → 自动降级回检疫期（防 tool poisoning），需重新人工放行。

### 2.3 安全工具目录（渗透/侦察类）

```python
from src.security.catalog import SafeCatalogRunner, load_catalog

runner = SafeCatalogRunner(load_catalog())
runner.set_scope(["example.com", "10.0.0.0/24"])   # 必须先声明授权目标
runner.allow_dangerous(True)                        # 主动攻击类需显式开启
result = runner.run("dns-lookup", target="sub.example.com")
```

硬门禁（按顺序）：
1. 未 `set_scope` → 任何执行直接拒绝
2. target 不在授权范围（域名后缀 / CIDR）→ 拒绝
3. `dangerous: true` 工具未 `allow_dangerous(True)` → 拒绝
4. 命令模板参数含 `;&|` 等注入字符 → 拒绝
5. 依赖的 CLI 二进制未安装 → 明确报"工具未安装"

内置目录见 `src/security/catalog/recon.yaml`，加工具 = 加一条 YAML。

### 2.4 推理模式 Python API

```python
from src.reasoning import run_reasoning, ReasoningConfig

result = run_reasoning(
    pattern="reflexion",          # 或 plan-execute / lats / debate
    task="逆向分析该二进制",
    llm=my_llm_fn,                # (system, user) -> str
    tool_executor=my_tools,       # (tool_name, args) -> str（默认走 clawd ToolRegistry）
    config=ReasoningConfig(max_iterations=8, max_tool_calls=30),
)
print(result.answer, result.confidence)
print(result.to_dict())           # 含全部步骤记录
```

## 三、验证矩阵（收口实测记录）

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 新增模块测试 | `venv/Scripts/python.exe -m pytest tests/mcp/ tests/reasoning/ tests/security/ tests/reverse_tools/ tests/agent/test_engine_extended_tools.py tests/cli_handlers/test_reason_handler.py -q` | **116 passed** |
| 契约测试 | `venv/Scripts/python.exe -m pytest tests/contracts/ -q` | 39 passed |
| CLI 真实调用 | `python -m src reason --help` | 命令注册成功 |
| ruff 硬指标 | `ruff check src/ tests/ --select F821,F811,E9` | All passed |
| 导入扫描 | `python scripts/import_sweep.py` | IMPORT-FAIL=0 |
| 测试收集 | `pytest tests/ --collect-only -q` | 0 errors |
| E2E 冒烟 | `python scripts/e2e_smoke.py` | 见 reports/ 变更报告 |

已知存量失败（与本次改动无关，基线复跑验证）：17 个 —— 12 个 Windows 缺 bash/echo（tests/tools_runtime/test_bash_execution_paths.py 等），5 个缺 redis 包（tests/core/test_cache.py）。

## 四、排障

| 现象 | 原因 | 处理 |
|------|------|------|
| `reason` 报 LLM 适配失败 | 未配置 API Key | 配置 litellm 支持的 provider 环境变量 |
| MCP server 工具没出现 | server 在检疫期 | 看 `.clawd/mcp_governance.json`，人工 `approve` |
| MCP server 工具突然消失 | 工具签名变更自动降级 | 检查 server 是否被篡改/升级，确认安全后重新 approve |
| 安全工具报"未设置授权 scope" | 未声明授权目标 | `runner.set_scope([...])`，仅限授权资产 |
| GhidraTool 报连接失败 | GhidraMCP 插件未启动 | 先在 Ghidra 里启动插件（默认 localhost:8080） |
| objdump/binwalk 报工具未安装 | CLI 不在 PATH | 安装对应二进制或 `shutil.which` 可见 |

## 五、已知限制

1. `clawd reason` 的 LLM 走 litellm.completion 直调，未复用 clawd 的 provider 路由/降级体系（P3）
2. MCP stdio 传输依赖官方 `mcp` 包的 stdio_client，Windows 下某些 server 需要 `cmd /c` 包装
3. 推理模式与 5 阶段 WorkflowEngine 未深度融合，目前独立运行
4. `skills/reverse/js-reverse/` 上游未声明 LICENSE，商用分发前需确认（见该目录 LICENSE-WARNING.md）
5. 快检中 17 个存量失败属环境治理（装 redis、修 Windows bash），不阻塞

## 六、回滚

全部改动未提交前：`git checkout -- src/ tests/ && git clean -fd src/mcp src/reasoning src/security src/reverse_tools skills/reverse`（会删除新增模块，不可逆，先确认）。
提交后回滚：`git revert <commit>`。
