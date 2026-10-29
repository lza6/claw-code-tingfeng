# 已知问题与风险

## P3（不阻塞交付）
1. js-reverse-skill 上游未声明 LICENSE — 商用分发前确认（skills/reverse/js-reverse/LICENSE-WARNING.md）
2. 17 个存量测试失败需环境治理: 安装 redis 包（5 个）+ Windows bash/echo 依赖（12 个）
3. reason 的 LLM 直调 litellm.completion，未走 clawd provider 路由/降级体系
4. 推理模式与 5 阶段 WorkflowEngine 未深度融合（当前 CLI 胶水接入）
5. MCP stdio 在 Windows 下某些 server 需 cmd /c 包装
6. mcp-gamehacking、hermes-agent 参考目录损坏（hermes 副本在 D:\参考项目\hermes-agent-tmp）

## 安全边界（持续有效）
- 安全工具 catalog 有 scope 门禁 + dangerous 双重确认，仅限授权测试目标
- MCP server 接入默认检疫期，签名变更自动降级，需人工 approve

## 挂机扫描 backlog（2026-10-28，Agent 管理 Agent 轮次 1）
来源：PI-Desktop / dsh-turn-rewind / Hermes-CN-Desktop，6 项目 8 分钟限时扫描。

### 高适用（建议下轮吸收）
1. **Turn 队列持久化 + 崩溃后 held 启动**（PI-Desktop turn-queue.ts）——崩溃续跑但恢复会话默认 held 不自动开工；目标：5 阶段工作流引擎加 QueueStore + restore-hold
2. **会话快照分页恢复**（PI-Desktop snapshotItems 50 页转写）——崩溃后按页恢复续聊；目标：memory SQLite 加 session snapshot 表
3. **剪贴板历史服务**（PI-Desktop clipboard-history.ts）——30天/500条/256MB/SHA256去重；目标：Electron 主进程移植
4. **Turn 级快照回退 Change Ledger**（dsh-turn-rewind）——恢复计划预览+救援点+哈希验证+失败自动回滚；目标：patch engine 上加恢复点 manifest 层

### 中适用（记一笔）
5. 通知抑制 fail-safe 一行纯函数（仅"窗口聚焦+正看该会话"才抑制）——桌面端加系统通知时采用
6. Hermes 三层热更新（Ed25519签名+staging+原子rename+minAppVersion地板）——UI 层免重启热更可借鉴；灰度放量无现成实现需自研（latest.json 加 rolloutPercent + 稳定哈希分桶）

### P3 概念
- dsh-mnemon 记忆空间可命名/激活；DSH-taskboard 的"Agent 只能提交 in_review、人工验收 done"权限边界

## 55 个"待拍板"模块已收敛为明确决策（2026-10-28）

原判定把 55 个不可达模块标为"需用户拍板"，长期悬空。已按证据逐簇裁定：
**全部保留**，理由与接线条件见 `计划书/死代码判定-2026-10-28.md` §九。

关键反转证据：v0.61.2 修复的 celery 相对导入 / 信号签名 / otel API 路径三个真实缺陷说明
"死码链"可能只是"未部署路径" → 机械删除会作废真实修复。

下一步应是**接线批次**（优先 hooks 体系 2,580 行，已有互补实现待注册进 core.hook_registry），
而不是继续删除批次。已接线完成项：`--dimension/-d` 维度引导（原为假开关，commit 6366578）。

## 挂机扫描 backlog 轮次 2（2026-10-28，主控 DIRECT 扫描）

来源：`D:\参考项目` 定向抽读（deepeval / LongHorizon-Harness / anthropics__sandbox-runtime / agent-systems-benchmark-state）。
不含轮次 1 已有 6 条（Turn 队列/会话快照/剪贴板/Change Ledger/通知抑制/热更新）。

### 高适用

1. **pytest 原生 LLM 评测集成**（来源 `deepeval`，DIRECT 读 README）
   做法：`assert_test(LLMTestCase(input, actual_output, expected_output), metric)` 直接作为 pytest 用例跑；
   metric 可组合（G-Eval 自定义评分标准 / answer-relevancy / hallucination）；数据集与用例分离，
   基线分数落库对比。**本项目缺 eval harness（计划书 W8）**，此模式可零新框架接入现有 pytest。
   成本：~300-400 行（metric 适配 + 数据集 loader + 基线比对）。需新依赖：可选（可先用启发式 metric 实现）。
   注意：真实调用 LLM 计费 → 必须 mock/录制，只在显式批准下小样本真实跑。

2. **轨迹录制 + 回放式 agent 回归**（来源 `LongHorizon-Harness`，DIRECT 读 README）
   做法：把每次 run 的 (plan → action → observation → verify) 序列持久化为 trajectory，
   回归时**回放 observation 固定模型输出**，只断言 agent 的决策分支与工具调用序列，
   从而让非确定性 LLM 的回归可重复。本项目 workflow engine 已有 run 状态目录（.clawd/runs/<id>），
   缺"工具调用序列断言层"。
   成本：~250-350 行（trajectory writer + replay harness + 断言 DSL）。无新依赖。

### 中适用

3. **plan→act→verify→checkpoint/recover 的一等公民化**（`LongHorizon-Harness`，DIRECT）
   本项目 5 阶段工作流已有阶段结果持久化，但 checkpoint 是"隐式"的；对方把 recover 作为显式阶段且
   有独立评分（WeaveBench/OSWorld/Terminal-Bench 对齐）。可借鉴其"恢复成功率"作为自身指标。

4. **状态文件三件套（CURRENT/PROJECT_STATE/PROVENANCE）**（`agent-systems-benchmark-state`，DIRECT 读文件列表）
   本项目已有 `workflow_status.md` 承担 CURRENT；缺 PROVENANCE（谁在何时基于什么证据改的状态）。
   低成本补充：在 workflow_status 每条验证记录后追加 `(证据: 命令 + exit code + 时间)`——本轮已在 test_ledger 实践。

### 不适用（明确排除）

- `anthropics__sandbox-runtime`：OS 级沙箱依赖 macOS `sandbox-exec` / Linux `bubblewrap`，**Windows 无对应原语**，
  本项目本机为 Windows 10；其 proxy-based 网络过滤思路可借鉴，但落地需另建代理层，成本 > 收益。
  本项目已有 Docker 沙箱（src/tools_runtime/sandbox/docker.py）+ MCP 检疫审批，安全边界不裸奔。

## 2026-10-29 本轮新增的已知限制（未闭环，需外部条件或后续排期）

1. **桌面安装包未签名**：`electron-builder` 日志 `no signing info identified, signing is skipped`。
   需要证书文件 + `CSC_LINK` / `CSC_KEY_PASSWORD`。未签名会触发 SmartScreen"未知发布者"。
2. **`src/hooks/`（2,541 行 / 10 模块）仍不可达**：判定为上游参考快照，见 ADR 0019。
   若要采用需按本项目重写契约（例如把 prompt guidance 断言改成我们自己的模板校验并进 CI）。
3. **`clawd review` 只看代码文本 + diff**：不执行代码、不看运行期行为（见 D-20 的代价）。
4. **`clawd explain` 的工具成败是启发式**：只扫描输出前 400 字符的失败标志；误判方向选"宁可放过"，
   所以 `ok` 只用于展示，不能作为对外"通过"承诺。
5. **`scripts/e2e_smoke.py` 本轮未跑**：真实 LLM 端点属付费红线（预算默认 0），需单独批准。
