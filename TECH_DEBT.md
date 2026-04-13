# 技术债务登记表


| ID | 优先级 | 问题 | 描述 | 文件 | 创建日期 | 解决日期 |
|----|--------|------|------|------|----------|----------|

| TD-0001 | high | QUALITY_DEBT_AUTO | 质量债务检测: TestGap=True, DocGap=True | src/workflow/healable_executor.py | 2026-04-12 | - |
| TD-0002 | medium | quality-debt-test | 检测到测试缺口：新修改的源文件缺少对应的测试用例。 | src/workflow/healable_executor.py | 2026-04-12 | - |
| TD-0003 | low | quality-debt-doc | 检测到文档缺口：核心逻辑变动未同步更新文档。 | src/workflow/healable_executor.py | 2026-04-12 | - |
| TD-0004 | high | quality-debt-complexity | 函数复杂度过高: Function 'execute_with_healing' cyclomatic/nested depth excessive (16) | src/workflow/healable_executor.py | 2026-04-12 | - |
| TD-0005 | high | quality-debt-complexity | 函数复杂度过高: Function '_execute_heal_strategy_with_feedback' cyclomatic/nested depth excessive (7) | src/workflow/healable_executor.py | 2026-04-12 | - |
| TD-0006 | high | quality-debt-complexity | 函数复杂度过高: Function 'execute_with_healing' too long (120 lines) | src/workflow/healable_executor.py | 2026-04-12 | - |
| TD-0007 | high | workflow-auto-failure | 未完成的修复: security.critical: 使用了不安全的 eval/exec | - | 2026-04-12 | - |
| TD-0008 | high | workflow-auto-failure | 未完成的修复: security.critical: 使用了不安全的 eval/exec | - | 2026-04-12 | - |
| TD-0009 | high | workflow-auto-failure | 未完成的修复: security.critical: 使用了不安全的 eval/exec | - | 2026-04-12 | - |
| TD-0010 | high | workflow-auto-failure | 未完成的修复: convention.high (122 个同类问题) | - | 2026-04-12 | - |
| TD-0011 | high | workflow-auto-failure | 未完成的修复: complexity.high (77 个同类问题) | - | 2026-04-12 | - |
| TD-0012 | high | workflow-auto-failure | 未完成的修复: convention.medium (416 个同类问题) | - | 2026-04-12 | - |
| TD-0013 | high | workflow-auto-failure | 未完成的修复: complexity.medium (81 个同类问题) | - | 2026-04-12 | - |
| TD-0014 | high | workflow-auto-failure | 未完成的修复: duplication.medium (2413 个同类问题) | - | 2026-04-12 | - |
| TD-0015 | high | workflow-auto-failure | 未完成的修复: convention.low (124 个同类问题) | - | 2026-04-12 | - |
