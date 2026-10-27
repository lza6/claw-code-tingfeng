# 技能: clawd 超级智能体扩展开发 SOP

## 适用场景
给 clawd 新增：外部工具集成（MCP）、推理模式、逆向工具、安全工具时遵循本流程。

## 前置读取
1. `workflow_status.md` — 当前状态与遗留事项
2. `docs/ENHANCEMENT_GUIDE.md` — 现有增强模块的架构与约定
3. `docs/MAINTENANCE.md` — Provider/Tool/CLI 扩展 SOP
4. `.agent/memory/known-issues.md` — 避免重复踩坑

## 新增 MCP server 接入
1. 写 `.clawd/mcp_servers.json` 条目（stdio 需 command；http 需 url）
2. `ToolGovernor().approve(name, note)` 放行（新 server 默认检疫期）
3. 启动 agent 会话验证工具出现（日志："MCP 桥接工具已装配: N 个"）
4. 验收：`mcp__<server>__<tool>` 可被 agent 调用；签名变更自动降级检疫

## 新增推理模式
1. 在 `src/reasoning/patterns.py` 加 `XxxPattern(BaseReasoningPattern)`，实现 `run(task) -> ReasoningResult`
2. 注册进 `PATTERNS` dict
3. `src/cli/entrypoint.py` reason 命令与 `src/main.py` subparser 同步加参数（两处必须一致）
4. 测试用 FakeLLM 脚本化（参考 tests/reasoning/test_patterns.py），禁止调真实 API
5. 验收：`python -m src reason <pattern> "任务"` 真实跑通

## 新增逆向/本地工具
1. `src/reverse_tools/` 新建工具类（BaseTool，execute 返回 ToolResult，不抛异常）
2. 加入 `get_all_tools()` 列表 → agent 引擎自动装配
3. 外部 CLI 工具必须 `shutil.which` 预检，未装时明确报错
4. 测试：真实 fixture + mock 外部进程，断言输出格式

## 新增安全工具目录条目
1. 编辑 `src/security/catalog/recon.yaml`（name/description/category/command 模板/tags）
2. 主动攻击类必须 `dangerous: true`（强制 allow_dangerous 门禁）
3. 模板占位符仅限 {target}/{port}/{extra}/{output}，注入字符自动拦截

## 验收标准（硬性）
- pytest 新增测试全绿；ruff F821/F811/E9 零错误；IMPORT-FAIL=0
- CLI 入口真实调用验证（--help + 一次实际执行）
- 文档同步：docs/ENHANCEMENT_GUIDE.md 相应章节

## 常见坑
- agent engine 的工具 dict 键是 `tool.name`（小写），不是类名
- `logger` 在 engine.py 是 `self.logger`，模块级没有 logger
- ToolRegistry（tool_interface.py 全局单例）与 AgentEngine.tools（实例 dict）是两套，MCP 桥接两边都要考虑
- Windows 下 Python 3.10 的 `asyncio.TimeoutError is TimeoutError` 为 False，except 两者都要写
- **CLI 双入口铁律**：clawd 命令有三处入口（Typer: src/cli/entrypoint.py、argparse: src/main.py、处理器: src/cli_handlers/ 或独立 handler）。加参数必须三处同步，漏一处 = 打包版/直调版行为不一致（踩过两次：reason 的 conclusion、serve 的 --env-file）
- 桌面打包依赖闭包要按"入口命令的运行时链"验证（typer→rich→markdown_it 这类 import 时链 AST 扫描扫不到），最终以 `bundle python -m src serve` 实跑为准
- venv 的 python.exe 是启动器（硬依赖 pyvenv.cfg），便携分发必须用系统 Python 的真解释器 + stdlib + venv site-packages 三件套
