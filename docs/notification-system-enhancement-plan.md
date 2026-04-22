# 通知系统增强实施计划

## 概述

将 oh-my-codex-main 的通知系统优秀特性迁移到 claw-code-tingfeng 项目。

## 当前状态

### A项目 (claw-code-tingfeng)
- ✅ 已有基础通知框架
- ✅ 支持 Discord Webhook, Telegram, Slack
- ❌ 缺少 Discord Bot API 支持
- ❌ 缺少会话注册表
- ❌ 缺少模板引擎
- ❌ 缺少冷却机制
- ❌ 缺少回复监听器

### B项目 (oh-my-codex-main)
- ✅ 完整14个模块的通知系统
- ✅ Discord Bot + Webhook 双重支持
- ✅ 会话注册表 (session-registry.ts)
- ✅ 模板引擎 (template-engine.ts)
- ✅ 冷却管理 (idle-cooldown.ts)
- ✅ 临时合同 (temp-contract.ts)
- ✅ 回复监听器 (reply-listener.ts)

---

## 实施步骤

### Step 1: 创建会话注册表 (session_registry.py)

**源文件**: `oh-my-codex-main/src/notifications/session-registry.ts`

**功能**:
- 跟踪平台消息ID到tmux pane的映射
- 支持回复关联
- 使用JSONL格式保证原子写入
- 跨进程锁机制

**目标文件**: `src/notifications/session_registry.py`

---

### Step 2: 创建模板引擎 (template_engine.py)

**源文件**: `oh-my-codex-main/src/notifications/template-engine.ts`

**功能**:
- `{{variable}}` 变量插值
- `{{#if var}}...{{/if}}` 条件处理
- 内置变量: event, sessionId, message, timestamp, projectName等
- 计算变量: duration, time, modesDisplay, footer等

**目标文件**: `src/notifications/template_engine.py`

---

### Step 3: 创建冷却管理器 (cooldown.py)

**源文件**: `oh-my-codex-main/src/notifications/idle-cooldown.ts`

**功能**:
- 空闲通知冷却
- 会话范围的状态文件
- 环境变量 + 配置文件双重控制
- 自动过期清理

**目标文件**: `src/notifications/cooldown.py`

---

### Step 4: 创建临时合同管理 (temp_contract.py)

**源文件**: `oh-my-codex-main/src/notifications/temp-contract.ts`

**功能**:
- 临时模式状态管理
- 会话生命周期绑定
- 自动清理

**目标文件**: `src/notifications/temp_contract.py`

---

### Step 5: 增强 dispatcher.py

**现有文件**: `src/notifications/dispatcher.py`

**增强内容**:
1. 添加 Discord Bot API 支持 (`send_discord_bot()`)
2. 集成会话注册表
3. 集成模板引擎
4. 集成冷却机制
5. 添加事件钩子调用

---

### Step 6: 更新 config.py

**现有文件**: `src/notifications/config.py`

**增强内容**:
1. 添加 Discord Bot 配置类
2. 添加会话注册表配置
3. 添加冷却配置
4. 添加事件特定配置
5. 支持环境变量覆盖

---

## 测试策略

每个模块都需要独立的单元测试:
- 模板引擎: 变量替换、条件处理、边界情况
- 会话注册表: 并发写入、锁机制、过期清理
- 冷却管理: 时间计算、会话隔离
- 分发器: 各平台发送逻辑

---

## 集成点

1. **主入口** (`src/main.py`): 初始化通知系统
2. **会话管理** (`src/session/`): 注册会话事件
3. **团队模式** (`src/team/`): 发送团队状态通知
4. **工作流引擎** (`src/workflow/`): 阶段完成通知

---

## 向后兼容

- 保持现有API不变
- 新功能通过配置开关控制
- 旧配置文件自动升级

---

## 预期收益

- ✅ 通知灵活性 +200%
- ✅ 减少通知泛滥 (冷却机制)
- ✅ 支持回复交互 (会话注册表)
- ✅ 消息模板化 (模板引擎)
- ✅ Discord Bot 集成

---

## 时间估算

- Step 1-3: 各2-3小时
- Step 4: 1-2小时
- Step 5-6: 3-4小时
- 测试: 2-3小时
- **总计**: 约15-20小时
