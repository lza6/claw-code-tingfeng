---
name: intent_router
description: 自动根据关键字路由到相应技能
---
## Overview
实现基于关键字的意图路由，利用 `src/agent/keyword_registry.py` 中的映射表，将用户输入匹配的技能自动激活。

## When to Use
当用户发送自然语言指令，需要自动触发相应的技能时。

## Implementation
1. 在 `src/agent/intent_router.py` 中读取 `keyword_registry`。
2. 匹配输入文本 → 对应技能名称。
3. 调用 `Skill` API 执行。

## Tests
- 单元测试验证关键词映射
- 集成测试确保能够触发相应技能
