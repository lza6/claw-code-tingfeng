---
name: keyword_registry
description: 关键词注册表，用于自动路由技能
---
## Overview
提供关键词到技能的映射，支持批量注册、优先级匹配、模式缓存和别名解析，是 Intent Router 与其他自动化系统的底层驱动。

## When to Use
- 需要根据用户自然语言关键字自动触发预定义技能时
- 实现多模态指令映射，如 “code review” → code-reviewer
- 需要动态更新关键词映射而不改动代码

## Implementation
1. 在 `src/agent/keyword_registry.py` 中定义 `KeywordEntry` 与 `KeywordRegistry`。
2. 使用 `@dataclass` 描述每条关键词条目，包含 `keyword`、`skill`、`priority`、`aliases`、`description` 等字段。
3. 通过 `register` / `register_batch` 方法向注册表添加条目。
4. `find_skill` 方法对输入文本进行优先级排序的子串匹配，并返回对应的 `skill` 名称。
5. `get_all_skills` 与 `get_skill_keywords` 供后端查询全部技能集合或关键字列表。
6. 默认注册表包含约 40 条关键词条目，支持自定义批量注册。

## Tests
- 单元测试验证关键词匹配的优先级与别名功能。
- 集成测试确保 `find_skill` 能在混合句子中准确识别并返回正确的技能。
- 性能基准测试测量模式缓存对大量关键词的查找时延。
