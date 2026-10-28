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
