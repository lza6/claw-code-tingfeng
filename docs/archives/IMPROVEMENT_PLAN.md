# Clawd Code (霆锋版) - 改进优化迭代计划指南

**项目**: Clawd Code (AI 编程代理框架)  
**版本**: v0.46.0  
**生成日期**: 2026-04-10  
**状态**: 待执行

---

## 一、项目当前状态概览

### 1.1 核心指标

| 指标 | 当前值 | 目标值 | 状态 |
|------|--------|--------|------|
| 测试通过率 | 100% (1565 passed) | ≥100% | ✅ 保持 |
| 项目健康度 | 9/10 | 10/10 | 🔄 提升中 |
| 测试覆盖率 | ~49% | ≥90% | ⚠️ 需改进 |
| 最大文件行数 | 468 (已拆分) | <400 | 🔄 持续优化 |
| >500行文件数 | 14 | <5 | 🔄 持续拆分 |

### 1.2 已完成工作

- ✅ workflow/engine.py 拆分 (1294→468行, -64%)
- ✅ cli/textual_dashboard.py Widgets 模块化
- ✅ 项目健康度从 8.5 提升至 9/10
- ✅ 向后兼容性 100%

---

## 二、待拆分大型文件清单 (14个)

根据 `task_plan.md`，剩余待拆分文件如下：

| 序号 | 文件路径 | 行数 | 难度 | 建议拆分策略 |
|------|----------|------|------|--------------|
| 1 | `src/cli/textual_dashboard.py` | 2118 | ⭐⭐⭐⭐⭐ | Widget模块化 (已完成部分) |
| 2 | `src/llm/__init__.py` | 1031 | ⭐⭐⭐⭐ | 按LLM提供商拆分 |
| 3 | `src/cli/repl.py` | 871 | ⭐⭐⭐⭐ | 命令处理器拆分 |
| 4 | `src/tools_runtime/bash_tool.py` | 849 | ⭐⭐⭐ | 平台功能拆分 |
| 5 | `src/agent/engine.py` | 836 | ⭐⭐⭐⭐ | 核心引擎模块化 |
| 6 | `src/screens/omni_glow_widgets.py` | 822 | ⭐⭐⭐⭐ | UI组件拆分 |
| 7 | `src/cli/aider_commands.py` | 816 | ⭐⭐⭐⭐ | Aider命令模块化 |
| 8 | `src/tools_runtime/linter.py` | 804 | ⭐⭐⭐ | Linting规则拆分 |
| 9 | `src/llm/model_info.py` | 804 | ⭐⭐⭐ | 模型元数据拆分 |
| 10 | `src/cli/tui/thinking_canvas.py` | 799 | ⭐⭐⭐⭐ | TUI组件拆分 |
| 11 | `src/core/git_integration.py` | 791 | ⭐⭐⭐ | Git操作模块化 |
| 12 | `src/rag/text_indexer.py` | 735 | ⭐⭐⭐ | 索引器拆分 |
| 13 | `src/core/settings.py` | 728 | ⭐⭐⭐ | 设置管理模块化 |
| 14 | `src/agent/swarm/engine.py` | 690 | ⭐⭐⭐ | Swarm引擎拆分 |

---

## 三、清理任务清单 (旧产物/垃圾文件)

### 3.1 已识别备份文件 (需删除)

```
src/cli/repl.py.backup
src/cli/repl.py.bak
src/cli/textual_dashboard.py.backup
src/cli/textual_dashboard.py.backup2
src/tools_runtime/bash_tool.py.backup
src/llm/__init__.py.bak (如存在)
src/core/output_compressor.py.backup
```

### 3.2 缓存/临时目录 (选择性清理)

| 目录 | 建议操作 |
|------|----------|
| `__pycache__/` | 保留 (运行时自动生成) |
| `.pytest_cache/` | 可清理 |
| `.ruff_cache/` | 可清理 |
| `htmlcov/` | 可清理 |
| `logs/` | 检查后清理 |
| `tmp/` | 检查后清理 |

### 3.3 遗留报告文件 (评估保留)

以下文件可能为旧版本遗留，需评估是否保留：

```
ARIPER_DELIVERY_REPORT.md
ARIPER_DELIVERY_REPORT_v046.md
ARIPER_FINAL_DELIVERY_v046.md
CLAWGOD_DEPTH_INTEGRATION_REPORT.md
FILE_SPLITTING_REPORT.md
FINAL_INTEGRATION_REPORT.md
INTEGRATION_REPORT.md
INTEGRATION_REPORT_ONYX.md
ONYX_INTEGRATION_COMPLETE.md
ONYX_INTEGRATION_PLAN.md
PROJECT_PROFILE.md
COMPLETION_REPORT.md
```

**建议**: 保留最新的 `FINAL_SUMMARY.md` 和 `CHANGELOG.md`，其余整合报告可归档至 `docs/archives/`。

---

## 四、测试覆盖率提升计划

### 4.1 当前覆盖率分析

- 目标: 90%+
- 当前: ~49%
- 差距: 41%

### 4.2 优先补测模块 (按重要性排序)

| 优先级 | 模块 | 当前覆盖率 | 建议目标 |
|--------|------|-----------|----------|
| P0 | `src/agent/` | 中等 | 85%+ |
| P0 | `src/llm/` | 中等 | 85%+ |
| P1 | `src/core/` | 中等 | 80%+ |
| P1 | `src/tools_runtime/` | 中等 | 80%+ |
| P2 | `src/rag/` | 低 | 70%+ |
| P2 | `src/memory/` | 低 | 70%+ |

### 4.3 测试用例补充策略

1. **边界条件测试**: 空输入、极限值、异常输入
2. **集成测试**: 模块间交互验证
3. **mock依赖**: 隔离外部依赖 (LLM API, 文件系统)
4. **参数化测试**: 覆盖多种配置组合

---

## 五、代码质量优化机会

### 5.1 高优先级 (P0)

| # | 问题 | 影响 | 解决方案 |
|---|------|------|----------|
| 1 | 测试覆盖率不足 | 质量风险 | 补充关键模块测试 |
| 2 | 错误处理不一致 | 用户体验差 | 统一错误码格式 |
| 3 | 日志系统不完善 | 故障排查难 | 结构化日志 |

### 5.2 中优先级 (P1)

| # | 问题 | 影响 | 解决方案 |
|---|------|------|----------|
| 4 | 缺少监控指标 | 性能黑盒 | Prometheus 指标 |
| 5 | 配置复杂度 | 部署困难 | 简化智能默认 |
| 6 | 类型检查 | 潜在bug | MyPy 严格模式 |

### 5.3 低优先级 (P2)

| # | 问题 | 影响 | 解决方案 |
|---|------|------|----------|
| 7 | 内存泄漏风险 | 长时间运行崩溃 | 内存分析 |
| 8 | 前端性能 | 加载慢 | 代码分割 |

---

## 六、执行计划 (分阶段)

### Phase 1: 清理与基线验证 (第1天)

- [ ] 删除备份文件 (见 3.1)
- [ ] 归档旧报告文件
- [ ] 运行完整测试套件，确认基线 100% 通过
- [ ] 生成覆盖率基线报告

### Phase 2: 大型文件拆分 (第2-7天)

按优先级顺序执行拆分:

1. **Day 2**: `llm/__init__.py` 拆分
   - 创建 `llm/providers/` 子目录
   - 按提供商分离代码 (OpenAI, Anthropic, LiteLLM等)

2. **Day 3**: `cli/repl.py` 拆分
   - 命令解析器独立模块
   - 各命令子模块

3. **Day 4**: `tools_runtime/bash_tool.py` 拆分
   - 平台检测模块
   - 命令执行器模块

4. **Day 5**: `agent/engine.py` 拆分
   - 消息处理模块
   - 工具执行模块
   - 会话管理模块

5. **Day 6-7**: 其他文件轮转拆分

**拆分原则**:
- 单模块 ≤ 400行
- 保留所有原有 API (向后兼容)
- 拆分后运行测试验证
- 使用委托模式保留迁移方法

### Phase 3: 测试覆盖提升 (第8-14天)

- [ ] 目标模块选择 (P0优先级)
- [ ] 补充单元测试
- [ ] 补充集成测试
- [ ] 覆盖率验证 ≥85%

### Phase 4: 代码质量优化 (第15-21天)

- [ ] 统一错误处理
- [ ] 结构化日志
- [ ] MyPy 严格模式检查
- [ ] Ruff 规则强化

### Phase 5: 验证与交付 (第22天)

- [ ] 完整测试套件通过
- [ ] 覆盖率目标达成
- [ ] 项目健康度评估
- [ ] 更新文档

---

## 七、关键决策点

### 7.1 拆分策略选择

**方案A: 按功能域拆分** (推荐)
- 将大文件按业务功能分离
- 优点: 职责清晰，易于理解
- 缺点: 需要较多重构

**方案B: 按字母序拆分**
- 简单按类/函数字母顺序分组
- 优点: 改动小，快速
- 缺点: 可能缺乏内聚性

### 7.2 测试框架选择

继续使用 `pytest` + `pytest-asyncio`，当前框架满足需求。

### 7.3 向后兼容性

所有拆分必须保留原有 `__init__.py` 导出，确保:
- 现有导入路径不变
- 现有测试用例不变
- 现有命令行参数不变

---

## 八、风险与缓解

### 8.1 风险识别

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 拆分破坏现有功能 | 中 | 高 | 完整测试套件验证 |
| 测试覆盖率提升困难 | 高 | 中 | 分模块逐步提升 |
| 向后兼容丢失 | 低 | 高 | 保留原API，委托模式 |

### 8.2 回滚计划

如拆分后出现问题:
1. 保留原文件备份
2. 使用 git revert 快速回滚
3. 分支开发，每模块独立提交

---

## 九、验证标准

### 9.1 成功标准

| 指标 | 验收值 |
|------|--------|
| 测试通过率 | 100% |
| 测试覆盖率 | ≥85% (核心模块) |
| 最大文件行数 | <400 |
| >500行文件数 | <5 |
| 项目健康度 | 10/10 |

### 9.2 质量检查清单

- [ ] 所有测试通过 (`pytest`)
- [ ] Lint 无错误 (`ruff check`)
- [ ] 格式化正确 (`ruff format`)
- [ ] 类型检查通过 (`mypy --strict` 可选)
- [ ] 向后兼容测试通过

---

## 十、文档更新清单

完成改进后需更新:

1. **CLAUDE.md** - 更新项目结构
2. **CHANGELOG.md** - 记录变更
3. **README.md** - 如有必要
4. **FINAL_SUMMARY.md** - 更新项目画像
5. 新建 **IMPROVEMENT_LOG.md** - 本次改进日志

---

## 附录: 命令参考

```bash
# 运行测试
python -m pytest tests/ -v --tb=short

# 运行测试 (简短输出)
python -m pytest tests/ --tb=short

# Lint 检查
ruff check src/

# 格式化
ruff format src/

# 覆盖率报告
python -m pytest tests/ --cov=src --cov-report=html

# 清理缓存
rm -rf __pycache__ src/__pycache__
rm -rf .pytest_cache
rm -rf .ruff_cache
```

---

**文档版本**: v1.0  
**维护人**: AI Agent  
**下次评审**: 改进完成后
