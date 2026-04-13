# 🚀 Clawd Code：AI 编程代理框架

> **"让 AI 像交响乐团一样协作，让编程像呼吸一样自然。"**

**当前版本**: v0.45.0（与 `pyproject.toml` 一致）| **测试**: ✅ 1353 个用例（`pytest --collect-only`）| **覆盖率**: ~49%（目标 60%）| **质量工具**: ruff、mypy（可选）、pytest-cov（见 `pyproject.toml`）| **CI/CD**: GitHub Actions

---

## 📋 目录

- [快速开始](#-快速开始)
- [核心功能](#-核心功能)
- [架构概览](#-架构概览)
- [API 参考](#-api-参考)
- [部署指南](#-部署指南)
- [测试](#-测试)
- [故障排查](#-故障排查)
- [CI/CD](#-cicd-流水线)

---

## 🚀 快速开始

### 环境要求
- Python 3.10+
- OpenAI 或 Anthropic API Key

### 一键启动
```bash
# Windows
start.bat

# Linux/Mac
bash start.sh
```

### Docker 部署
```bash
docker-compose up -d
```

---

## 🧠 核心功能

### 1. 多 Agent 协作 (Swarm Intelligence)
将复杂任务分解，由专业 Agent 协同处理：
- **Orchestrator**: 任务分解与调度
- **Worker**: 代码实现
- **Auditor**: 代码审计
- **Integrator**: 结果集成

### 2. 自我修复 (Self-Healing)
错误自动感知与 AI 驱动的无干预修复循环。

### 3. 世界模型 (World Model)
代码库全景感知，依赖图谱 + 语义索引。

### 4. 企业级长短期记忆 (LTM)
基于 SQLite 的持久化模式存储与经验复用。

### 5. 高性能索引与 RAG (Enterprise-Grade RAG)
- **Trigram v2 索引**: 毫秒级全量代码搜索，告别逐文件 GREP。
- **全局符号表**: O(1) 跨文件符号定义查找。
- **结构化截断**: 智能避开函数定义边界的截断算法，保留代码语义。

### 6. 企业级韧性与观测 (Resilience & Observability)
- **自动重试机制**: 带有指数退避的 MCP/Bash 调用自愈。
- **结构化日志**: JSON 格式的遥测日志，支持自动化分析。

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                     用户交互层 (CLI/TUI)                  │
├─────────────────────────────────────────────────────────┤
│  REPL  │  Textual TUI  │  Rich HUD  │  Streaming Markdown │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                     核心引擎层                             │
├─────────────────────────────────────────────────────────┤
│  AgentEngine  │  SwarmEngine  │  SelfHealingEngine      │
└─────────────────────────────────────────────────────────┘
        │                    │                    │
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   Agent 层    │  │   记忆/认知层  │  │   工具运行时   │
├───────────────┤  ├───────────────┤  ├───────────────┤
│ Orchestrator  │  │ WorldModel    │  │ BashTool      │
│ Worker        │  │ EnterpriseLTM │  │ FileReadTool  │
│ Auditor       │  │ DependencyGraph│ │ FileEditTool  │
└───────────────┘  └───────────────┘  └───────────────┘
```

---

## 📚 API 参考

### 启动对话
```bash
python -m src.main chat
```

### 运行工作流
```bash
python -m src.main workflow run --goal "实现用户认证功能"
```

### 成本报告
```bash
python -m src.main cost-report
```

### 环境诊断
```bash
python -m src.main doctor
```

---

## 🐳 部署指南

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | OpenAI API 密钥 | - |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | - |
| `CLAWD_LOG_LEVEL` | 日志级别 | `info` |
| `CLAWD_WORKDIR` | 工作目录 | 当前目录 |

### Docker Compose
```yaml
services:
  clawd:
    build: .
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./workdir:/app/workdir
```

---

## 🧪 测试

### 运行全部测试
```bash
python -m pytest tests/ -v
```

### 测试覆盖率
```bash
python -m pytest tests/ --cov=src --cov-report=html
```

### 当前测试状态

| 指标 | 说明 |
|------|------|
| 用例总数 | **1192**（以 `python -m pytest --collect-only -q` 最后一行输出为准） |
| 总覆盖率 | **~49%**（目标 > 60%） |
| 执行 | `python -m pytest`（全量）；模块级覆盖率与分模块说明见 `htmlcov/` |

---

## 🚀 CI/CD 流水线

项目已集成 GitHub Actions 实现自动化 CI/CD：

### 持续集成 (CI)
- **触发条件**: push 到 main/develop，PR
- **执行步骤**:
  1. Lint 检查 (Ruff)
  2. 类型检查 (MyPy)
  3. 测试运行 (pytest)
  4. 覆盖率报告 (Codecov)
  5. 安全扫描 (Bandit + Safety)
  6. Docker 构建测试

### 持续部署 (CD)
- **触发条件**: 发布新版本 tag
- **执行步骤**:
  1. 多平台 Docker 镜像构建 (linux/amd64, linux/arm64)
  2. 推送到 GitHub Container Registry
  3. 自动版本标签

### 依赖自动更新
- **Dependabot**: 每周自动检查 pip/GitHub Actions/Docker 依赖更新
- **自动 PR**: 发现更新时自动创建 PR 供审查

### 本地开发命令
```bash
make install        # 安装依赖
make test           # 运行测试
make lint           # 代码 lint
make format         # 代码格式化
make type-check     # 类型检查
make coverage       # 覆盖率报告
make check          # 全量检查（CI 本地模拟）
make docker-build   # 构建 Docker 镜像
```

---

## 🆕 v0.44.0 新增功能

### ClawGod 整合
本次版本整合了 [ClawGod](https://github.com/0Chencc/clawgod) 项目的优秀设计：

#### 1. 声明式补丁引擎
```python
from src.core.patch_engine import PatchEngine, create_patch

engine = PatchEngine(target_file="path/to/file.py")
result = engine.dry_run_patches([patch])  # 预览
result = engine.apply_patches([patch])    # 应用
result = engine.revert_patches()          # 还原
```

#### 2. 上下文指纹验证
```python
from src.utils.context_validator import validate_match_context

result = validate_match_context(
    code=full_code,
    match_str=matched_string,
    keywords=['growthBook'],
)
if result.is_valid:
    print("验证通过！")
```

#### 3. 配置注入器 (6 层优先级)
```python
from src.core.settings import set_runtime_config, get_runtime_config

set_runtime_config("llm_model", "gpt-4o")
model = get_runtime_config("llm_model")
```

#### 4. Prompt 优化器
```python
from src.llm.prompt_optimizer import optimize_prompt

result = optimize_prompt(original_prompt, dry_run=True)
print(result.optimized_prompt)
```

### 关键指标提升
| 维度 | v0.43.0 | v0.44.0 | 提升 |
|------|---------|---------|------|
| 测试数量 | 743 | **1192** | +60% |
| 测试覆盖率 | 35% | **~49%** | +14% |
| CI/CD | ❌ | ✅ | 新增 |
| 代码重复 | 18KB | **0KB** | 消除 |
| 配置优先级 | 5 层 | **6 层** | +1 层 |
| 代码修改安全 | 手动 | **补丁引擎** | 10x |

---

## 🔧 故障排查

### 常见问题

#### Q: API 调用失败
**A**: 检查 `.env` 文件中 API Key 是否正确配置。

#### Q: 内存占用过高
**A**: 调整 `max_context_tokens` 参数限制上下文大小。

#### Q: 工具执行超时
**A**: 设置环境变量 `COMMAND_TIMEOUT=120` 增加超时时间。

---

## 📄 许可证

MIT License