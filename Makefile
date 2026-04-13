.PHONY: help install test lint format type-check coverage clean docker-build docker-run

# 默认目标
help:
	@echo "Clawd Code - 开发便捷命令"
	@echo ""
	@echo "可用命令:"
	@echo "  make install        安装项目依赖"
	@echo "  make test           运行测试"
	@echo "  make lint           代码 lint 检查"
	@echo "  make format         代码格式化"
	@echo "  make type-check     类型检查"
	@echo "  make coverage       测试覆盖率报告"
	@echo "  make clean          清理临时文件"
	@echo "  make docker-build   构建 Docker 镜像"
	@echo "  make docker-run     运行 Docker 容器"
	@echo ""

# 安装依赖
install:
	pip install --upgrade pip
	pip install -e ".[dev]"
	pre-commit install

# 运行测试
test:
	pytest tests/ -v --tb=short

# 代码 lint 检查
lint:
	ruff check src/ tests/

# 代码格式化
format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

# 类型检查
type-check:
	mypy src/ --ignore-missing-imports

# 测试覆盖率报告
coverage:
	pytest tests/ --cov=src --cov-report=html --cov-report=term-missing
	@echo ""
	@echo "覆盖率报告已生成到 htmlcov/index.html"

# 清理临时文件
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ coverage.xml .coverage
	rm -rf dist/ build/ *.egg-info

# 构建 Docker 镜像
docker-build:
	docker build -t clawd-code:latest .

# 运行 Docker 容器
docker-run:
	docker run --rm -it clawd-code:latest

# 全量检查（CI 本地模拟）
check: lint type-check test
	@echo ""
	@echo "✅ 所有检查通过！"
