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
    CLAWD_LOG_LEVEL=info

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

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; from src.utils.features import features; sys.exit(0)" || exit 1

# 暴露端口（WebSocket 远程访问）
EXPOSE 8765

# 入口点
ENTRYPOINT ["clawd"]
CMD ["chat"]
