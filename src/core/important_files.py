"""重要文件识别模块 — 从 Aider special.py 移植

识别代码库中的重要文件（配置文件、依赖文件、文档等）。

核心功能:
- is_important(): 判断单个文件是否为重要文件
- filter_important_files(): 批量过滤重要文件

用法:
    from src.core.important_files import is_important, filter_important_files

    if is_important('package.json'):
        print("是重要文件")

    important = filter_important_files(['README.md', 'test.py', 'src/main.py'])
"""
from __future__ import annotations

import os

# 重要文件列表（从 Aider special.py 移植并扩展）
ROOT_IMPORTANT_FILES: list[str] = [
    # 版本控制
    ".gitignore",
    ".gitattributes",
    # 文档
    "README",
    "README.md",
    "README.txt",
    "README.rst",
    "CONTRIBUTING",
    "CONTRIBUTING.md",
    "LICENSE",
    "LICENSE.md",
    "CHANGELOG",
    "CHANGELOG.md",
    "CODEOWNERS",
    # 包管理和依赖
    "requirements.txt",
    "Pipfile",
    "Pipfile.lock",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "composer.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "build.sbt",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "mix.exs",
    "rebar.config",
    "project.clj",
    "Podfile",
    "Cartfile",
    "dub.json",
    "dub.sdl",
    # 配置和设置
    ".env",
    ".env.example",
    ".env.local",
    ".editorconfig",
    "tsconfig.json",
    "jsconfig.json",
    ".babelrc",
    "babel.config.js",
    ".eslintrc",
    ".eslintignore",
    ".prettierrc",
    ".stylelintrc",
    "tslint.json",
    ".pylintrc",
    ".flake8",
    ".rubocop.yml",
    ".scalafmt.conf",
    ".dockerignore",
    ".gitpod.yml",
    "sonar-project.properties",
    "renovate.json",
    "dependabot.yml",
    ".pre-commit-config.yaml",
    "mypy.ini",
    "tox.ini",
    ".yamllint",
    "pyrightconfig.json",
    # 构建和编译
    "webpack.config.js",
    "rollup.config.js",
    "parcel.config.js",
    "gulpfile.js",
    "Gruntfile.js",
    "build.xml",
    "build.boot",
    "project.json",
    "build.cake",
    "MANIFEST.in",
    # 测试
    "pytest.ini",
    "phpunit.xml",
    "karma.conf.js",
    "jest.config.js",
    "cypress.json",
    ".nycrc",
    ".nycrc.json",
    # CI/CD
    ".travis.yml",
    ".gitlab-ci.yml",
    "Jenkinsfile",
    "azure-pipelines.yml",
    "bitbucket-pipelines.yml",
    "appveyor.yml",
    "circle.yml",
    ".circleci/config.yml",
    ".github/dependabot.yml",
    "codecov.yml",
    ".coveragerc",
    # Docker 和容器
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.override.yml",
    # 云和无服务器
    "serverless.yml",
    "firebase.json",
    "now.json",
    "netlify.toml",
    "vercel.json",
    "app.yaml",
    "terraform.tf",
    "main.tf",
    "cloudformation.yaml",
    "cloudformation.json",
    "ansible.cfg",
    "kubernetes.yaml",
    "k8s.yaml",
    # 数据库
    "schema.sql",
    "liquibase.properties",
    "flyway.conf",
    # 框架特定
    "next.config.js",
    "nuxt.config.js",
    "vue.config.js",
    "angular.json",
    "gatsby-config.js",
    "gridsome.config.js",
    # API 文档
    "swagger.yaml",
    "swagger.json",
    "openapi.yaml",
    "openapi.json",
    # 开发环境
    ".nvmrc",
    ".ruby-version",
    ".python-version",
    "Vagrantfile",
    # 质量和指标
    ".codeclimate.yml",
    # 文档
    "mkdocs.yml",
    "_config.yml",
    "book.toml",
    "readthedocs.yml",
    ".readthedocs.yaml",
    # 包注册表
    ".npmrc",
    ".yarnrc",
    # Lint 和格式化
    ".isort.cfg",
    ".markdownlint.json",
    ".markdownlint.yaml",
    # 安全
    ".bandit",
    ".secrets.baseline",
    # 其他
    ".pypirc",
    ".gitkeep",
    ".npmignore",
]

# 预计算标准化集合
NORMALIZED_ROOT_IMPORTANT_FILES: set[str] = {
    os.path.normpath(path) for path in ROOT_IMPORTANT_FILES
}

# 额外的扩展名模式（文件类型判断）
IMPORTANT_EXTENSIONS: set[str] = {
    # 配置文件
    ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf",
    ".properties", ".env", ".config", ".rc",
    # 脚本
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    # 文档
    ".md", ".rst", ".txt", ".adoc",
    # 容器
    "Dockerfile", "Dockerfile.dev", "Dockerfile.prod",
}


def is_important(file_path: str) -> bool:
    """判断文件是否为重要文件

    参数:
        file_path: 文件路径（可以是相对路径或绝对路径）

    返回:
        是否为重要文件
    """
    file_name = os.path.basename(file_path)
    dir_name = os.path.normpath(os.path.dirname(file_path))
    normalized_path = os.path.normpath(file_path)

    # 检查 GitHub Actions 工作流文件
    if dir_name == os.path.normpath(".github/workflows") and file_name.endswith(".yml"):
        return True

    # 检查标准化列表
    if normalized_path in NORMALIZED_ROOT_IMPORTANT_FILES:
        return True

    # 检查扩展名（对于配置文件）
    if file_name in IMPORTANT_EXTENSIONS:
        return True

    # 检查 .github 目录下的配置文件
    return bool(dir_name == os.path.normpath(".github") and file_name.endswith((".yml", ".yaml", ".json")))


def filter_important_files(file_paths: list[str]) -> list[str]:
    """过滤出重要文件

    参数:
        file_paths: 文件路径列表

    返回:
        重要文件列表
    """
    return [f for f in file_paths if is_important(f)]


def get_importance_score(file_path: str) -> float:
    """获取文件重要性分数

    参数:
        file_path: 文件路径

    返回:
        重要性分数 (0.0 - 1.0)
    """
    file_name = os.path.basename(file_path)
    normalized_path = os.path.normpath(file_path)
    dir_name = os.path.normpath(os.path.dirname(file_path))

    score = 0.0

    # 根目录配置文件最高优先级
    if dir_name in ("", ".", os.path.normpath(os.getcwd())):
        if normalized_path in NORMALIZED_ROOT_IMPORTANT_FILES:
            score = 1.0
        elif file_name in ROOT_IMPORTANT_FILES:
            score = 0.9

    # .github/workflows 下的文件
    if dir_name == os.path.normpath(".github/workflows"):
        score = 0.95

    # 其他重要文件
    if is_important(normalized_path):
        score = max(score, 0.7)

    return score


def sort_by_importance(file_paths: list[str], descending: bool = True) -> list[str]:
    """按重要性排序文件

    参数:
        file_paths: 文件路径列表
        descending: 是否降序（从高到低）

    返回:
        排序后的文件列表
    """
    scored = [(f, get_importance_score(f)) for f in file_paths]
    scored.sort(key=lambda x: x[1], reverse=descending)
    return [f for f, _ in scored]


# ==================== 便捷函数 ====================

def is_config_file(file_path: str) -> bool:
    """判断是否为配置文件"""
    file_name = os.path.basename(file_path)
    config_patterns = (
        ".env",
        "package.json",
        "pyproject.toml",
        "setup.py",
        "requirements.txt",
        "Dockerfile",
    )
    return file_name in config_patterns or file_name.startswith(".eslintrc") or file_name.startswith(".prettierrc")


def is_documentation(file_path: str) -> bool:
    """判断是否为文档文件"""
    doc_extensions = (".md", ".rst", ".txt", ".adoc")
    doc_files = ("README", "CONTRIBUTING", "CHANGELOG", "LICENSE")
    name = os.path.basename(file_path)
    return name.upper().startswith(doc_files) or name.lower().endswith(doc_extensions)


def is_dependency_file(file_path: str) -> bool:
    """判断是否为依赖文件"""
    dep_files = (
        "requirements.txt",
        "Pipfile",
        "package.json",
        "yarn.lock",
        "go.mod",
        "Cargo.toml",
        "Gemfile",
    )
    return os.path.basename(file_path) in dep_files


# 导出
__all__ = [
    "ROOT_IMPORTANT_FILES",
    "filter_important_files",
    "get_importance_score",
    "is_config_file",
    "is_dependency_file",
    "is_documentation",
    "is_important",
    "sort_by_importance",
]
