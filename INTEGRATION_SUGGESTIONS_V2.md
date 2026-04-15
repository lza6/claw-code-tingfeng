# 整合建议清单 V3

## 项目 A: claw-code-tingfeng (本地)
## 项目 B: oh-my-codex-main (同目录下)

---

## ✅ 已完成整合

### V2 历史 (2026-04-14)
- Catalog 模块 (43 skills, 39 agents)
- Templates 模块 (5种模板)
- CLI Config Enhancer
- Mode Context

### V3 本次新增 (2026-04-15)

| 模块 | 文件 | 状态 |
|------|------|------|
| Session History Search | src/session_history/search.py | ✅ 增强 |
| Idle Nudge | src/team/idle_nudge.py | ✅ 新建 |
| Team Init | src/team/__init__.py | ✅ 更新 |

---

## 📋 本次修改文件清单

### 修改文件 (4个)
```
src/session_history/
└── search.py                       # 增强: 日期过滤、项目过滤、snippet

src/team/
├── __init__.py                     # 更新: 导出idle_nudge
└── idle_nudge.py                   # 新建: 空闲提醒机制

src/workflow/
└── mode_context.py                 # 已存在 (V2完成)
```

### 新增功能详情

#### 1. Session History Search 增强
- `parse_since_spec()` - 解析时间规格 (7d, 24h, 1w)
- `clamp_integer()` - 数值范围限制
- `normalize_project_filter()` - 项目过滤标准化
- `build_snippet()` - 构建搜索上下文片段
- 日期范围过滤 (date_from, date_to)
- 项目/会话ID过滤
- 大小写敏感选项
- 上下文窗口 (context)

#### 2. Idle Nudge 机制
- `NudgeConfig` - 配置类
- `NudgeTracker` - 追踪器类
- `capture_pane()` - 捕获tmux pane
- `pane_looks_ready()` - 检测pane是否ready
- `pane_has_active_task()` - 检测活跃任务
- `is_pane_idle()` - 空闲检测
- `send_to_worker()` - 发送消息到worker

---

## 🎯 不重复造轮子

已跳过 (功能重叠):
- Autoresearch Runtime (Python已有)
- Pipeline Stages (Python已有)
- MCP State Server (Python已有基础版)
- Skills目录 (参考即可)

---

## ✅ 整合完成