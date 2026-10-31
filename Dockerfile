# Clawd Code (霆锋版) — 多阶段构建
# 企业级 Docker 配置，包含构建和运行阶段

# ---- 构建阶段 ----
FROM python:3.11-slim AS builder

WORKDIR /build

# 复制依赖文件
COPY requirements.txt pyproject.toml ./

# 安装构建依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
# 先拷源码再装自身：此前是 `pip install .` 在**没有任何源码**的目录里执行，
# 结果是"装出一个空的 clawd_code dist-info"——镜像能构建成功，但容器一启动就
# `ModuleNotFoundError: No module named 'src'`（v0.90.0 实测踩到）。
COPY src ./src
COPY prompts ./prompts
# 注意：这里**不能**加 `--no-deps`。requirements.txt 与 pyproject.toml 存在漂移
# （实测：`typer` 只在 pyproject 里，requirements.txt 没有），只按 requirements 装依赖
# 会得到一个启动就 `ModuleNotFoundError: No module named 'typer'` 的镜像。
# 以 pyproject 为准装自身 + 依赖；requirements.txt 继续留着给 pip-audit 做漏洞扫描。
RUN pip install --no-cache-dir --prefix=/install .

# ---- 运行阶段 ----
FROM python:3.11-slim

LABEL maintainer="Clawd Code Contributors"
LABEL description="AI 编程代理框架 - 多 LLM 提供商 + 工具调用 + RAG + WebSocket 远程访问"
LABEL version="0.39.0"

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLAWD_ENV=production \
    CLAWD_LOG_LEVEL=info \
    PYTHONPATH=/app \
    AGENT_SERVER_HOST=0.0.0.0
# AGENT_SERVER_HOST=0.0.0.0：服务默认绑 127.0.0.1，容器里等于端不出容器 ->
# 端口映射与健康检查全都不通（"远程访问"名不副实）。镜像内显式绑全部网卡。
# PYTHONPATH=/app：`COPY . .` 的代码在 /app，而 console script 从 /usr/local/bin 启动，
# 不靠 cwd 才能 import；同时也保证即使 site-packages 里那份失效仍能跑。

WORKDIR /app

# 从构建阶段复制依赖
COPY --from=builder /install /usr/local

# 复制应用代码
COPY --chown=1000:1000 . .

# 创建必要的目录
RUN mkdir -p /app/logs /app/.clawd /app/.clawd/experience && \
    chown -R 1000:1000 /app/logs /app/.clawd

# 非 root 用户运行
USER 1000:1000

# 健康检查：打真实存活端点 `/healthz`（免 token，只回答"进程还在跑"）
# 旧写法 `python -c "...features...; sys.exit(0)"` 只是 import 一个模块就返回 0，
# 无论 Host 有没有起来都算健康 —— 等于没有健康检查（编排系统永远不会重启坏容器）。
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=5).status == 200 else 1)"

# 暴露端口（WebSocket 远程访问）
EXPOSE 8765

# 入口点：默认跑 Host 服务（`serve`）。
# 默认 `chat` 是交互式命令、**不监听任何端口** —— 与上面的 EXPOSE/健康检查自相矛盾。
# 需要交互式会话时显式覆盖：`docker run -it clawd-code chat`
ENTRYPOINT ["clawd"]
CMD ["serve", "--port", "8765"]
