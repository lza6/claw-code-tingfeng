"""重要文件识别 — 从 Aider special.py 移植

识别项目根目录中的关键配置文件，这些文件应该优先包含在代码库上下文中。

支持的文件类型:
- 版本控制: .gitignore, .gitattributes
- 文档: README, CONTRIBUTING, LICENSE, CHANGELOG, SECURITY, CODEOWNERS
- 包管理: requirements.txt, package.json, pyproject.toml, setup.py, go.mod, Cargo.toml
- 配置: .env, .editorconfig, tsconfig.json, eslint, prettier
- 构建: webpack.config.js, Dockerfile, docker-compose.yml
- 测试: pytest.ini, jest.config.js
- CI/CD: .github/workflows/, .gitlab-ci.yml
"""

from pathlib import Path

# ==================== 重要文件列表 ====================

ROOT_IMPORTANT_FILES: list[str] = [
    # Version Control
    '.gitignore', '.gitattributes',
    # Documentation
    'README', 'README.md', 'README.txt', 'README.rst',
    'CONTRIBUTING', 'CONTRIBUTING.md', 'CONTRIBUTING.txt', 'CONTRIBUTING.rst',
    'LICENSE', 'LICENSE.md', 'LICENSE.txt',
    'CHANGELOG', 'CHANGELOG.md', 'CHANGELOG.txt', 'CHANGELOG.rst',
    'SECURITY', 'SECURITY.md', 'SECURITY.txt',
    'CODEOWNERS',
    # Package Management
    'requirements.txt', 'requirements-dev.txt',
    'Pipfile', 'Pipfile.lock',
    'pyproject.toml', 'setup.py', 'setup.cfg',
    'package.json', 'package-lock.json', 'yarn.lock',
    'go.mod', 'go.sum',
    'Cargo.toml', 'Cargo.lock',
    'Gemfile', 'Gemfile.lock',
    'composer.json', 'composer.lock',
    'pom.xml', 'build.gradle', 'build.gradle.kts',
    # Configuration
    '.env', '.env.example', '.env.local', '.editorconfig',
    'tsconfig.json', 'jsconfig.json',
    '.eslintrc', '.eslintignore', '.prettierrc',
    '.pylintrc', '.flake8', 'mypy.ini', 'tox.ini',
    '.pre-commit-config.yaml',
    # Build
    'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
    'Makefile', 'CMakeLists.txt',
    'MANIFEST.in',
    # Testing
    'pytest.ini', 'jest.config.js',
    # CI/CD
    '.github', '.gitlab-ci.yml', '.travis.yml',
    'Jenkinsfile', 'cloudbuild.yaml',
]


def is_important_file(fname: str) -> bool:
    """检查文件名是否为重要文件

    参数:
        fname: 文件名（可包含路径）

    返回:
        是否为重要文件
    """
    name = Path(fname).name

    # 精确匹配
    if name in ROOT_IMPORTANT_FILES:
        return True

    # 目录匹配
    if name in ('.github', '.gitlab', 'bitbucket-pipelines'):
        return True

    # 常见隐藏配置文件模式
    return bool(name.startswith('.') and len(name) > 2 and any(name.endswith(ext) for ext in ['.yaml', '.yml', '.json', '.rc', '.config', '.conf', '.toml', '.ini', '.cfg']))


def get_important_files(root_dir: str | Path) -> list[str]:
    """扫描目录获取所有重要文件

    参数:
        root_dir: 项目根目录

    返回:
        重要文件路径列表（相对于 root_dir）
    """
    root = Path(root_dir)
    result: list[str] = []

    for name in ROOT_IMPORTANT_FILES:
        path = root / name
        if path.is_file():
            result.append(name)
            continue

        # 检查大小写变体
        if path.stem:
            for variant in [name, path.stem, path.stem.upper(), path.stem.lower()]:
                vpath = root / variant
                if vpath.is_file():
                    result.append(variant)
                    break

    # 检查特殊目录
    for dirname in ('.github', '.gitlab', 'bitbucket-pipelines'):
        if (root / dirname).is_dir():
            result.append(dirname + '/')

    return result
