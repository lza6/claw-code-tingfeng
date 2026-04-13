# Clawd Code 记忆存储结构 (Storage Structure)

> 注意：本项目目前采用基于文件的 JSON 持久化存储，位于 `.clawd/memory/` 目录下。

## 1. 记忆条目 (MemoryEntry) - `entries.json`
存储统一的记忆条目，支持多种类型和来源。

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| id | str | 唯一标识 (UUID) |
| memory_type | enum | 记忆类型 (semantic, episodic, working) |
| kind | enum | 细粒度分类 (fact, procedure, pitfall, secret_ref, success_prior) |
| content | str | 记忆核心内容 |
| source | enum | 记忆来源 (user_feedback, implementation, review, etc.) |
| importance | float | 重要性评分 (0.0 - 1.0) |
| tags | list[str] | 标签列表 |
| selectors | dict | 检索选择器 (project, environment, tool) |
| evidence | list[dict] | 证据列表 (kind, path) |
| metadata | dict | 扩展元数据 |
| created_at | float | 创建时间戳 |
| updated_at | float | 更新时间戳 |
| access_count | int | 访问次数 |
| verification_state | str | 验证状态 (unverified, verified, contradicted) |
| confidence | str | 置信度 (low, medium, high) |

## 2. 语义模式 (SemanticPattern) - `patterns.json`
存储跨上下文复用的抽象模式和规则。

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| id | str | 唯一标识 |
| name | str | 模式名称 |
| category | str | 分类 |
| pattern | str | 模式描述 |
| problem | str | 解决的问题 |
| solution | str | 解决方案 |
| confidence | float | 置信度 |
| applications | int | 应用次数 |

## 3. 情景记忆 (EpisodicMemory) - `episodic/*.json`
记录特定时间、场景下的具体经验。

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| id | str | 唯一标识 |
| timestamp | float | 时间戳 |
| skill_used | str | 使用的技能名称 |
| situation | str | 情况描述 |
| root_cause | str | 根本原因 |
| solution | str | 解决方案 |
| lesson | str | 教训/经验 |

## 4. 工作记忆 (WorkingMemory) - `working.json`
当前会话的临时上下文数据。

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| session_id | str | 会话 ID |
| data | dict | 键值对存储 |
| created_at | float | 创建时间 |
