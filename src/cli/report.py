"""报告生成 — 从 Aider report.py 移植

自动收集系统信息、环境状态，生成 GitHub issue URL。

用法:
    from src.cli.report import generate_report, open_github_issue
    generate_report(error_text='Bug description here')
    open_github_issue(error_text='Bug description here', title='Bug: xxx')
"""
from __future__ import annotations

import platform
import subprocess
import sys
import urllib.parse
import webbrowser
from typing import Any

# ==================== 系统信息收集 ====================

def get_python_info() -> str:
    """获取 Python 环境信息"""
    implementation = platform.python_implementation()
    is_venv = sys.prefix != sys.base_prefix
    return f'Python: {platform.python_version()} ({implementation}), venv={is_venv}'


def get_os_info() -> str:
    """获取操作系统信息"""
    return f'OS: {platform.system()} {platform.release()} ({platform.architecture()[0]})'


def get_git_info() -> str:
    """获取 Git 信息"""
    try:
        git_version = subprocess.check_output(
            ['git', '--version'], stderr=subprocess.DEVNULL
        ).decode().strip()
        return f'Git: {git_version}'
    except Exception:
        return 'Git: not found'


def get_clawcode_version() -> str:
    """获取 ClawCode 版本"""
    try:
        version_file = Path(__file__).parent.parent.parent / 'VERSION'
        if version_file.exists():
            return f'ClawCode: {version_file.read_text().strip()}'
    except Exception:
        pass
    return 'ClawCode: unknown'


def get_dependency_info() -> str:
    """获取关键依赖版本"""
    deps: list[str] = []

    for mod_name, display_name in [
        ('aider', 'aider'),
        ('litellm', 'litellm'),
        ('tree_sitter', 'tree-sitter'),
        ('tree_sitter_languages', 'tree-sitter-languages'),
        ('networkx', 'networkx'),
        ('diskcache', 'diskcache'),
        ('httpx', 'httpx'),
        ('playwright', 'playwright'),
        ('rich', 'rich'),
        ('prompt_toolkit', 'prompt-toolkit'),
    ]:
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, '__version__', 'installed')
            deps.append(f'{display_name}={ver}')
        except ImportError:
            deps.append(f'{display_name}=not installed')

    return 'Dependencies: ' + ', '.join(deps)


def get_system_info() -> str:
    """收集所有系统信息"""
    return '\n'.join([
        get_clawcode_version(),
        get_python_info(),
        get_os_info(),
        get_git_info(),
        get_dependency_info(),
    ])


# ==================== 报告生成 ====================

def generate_report(
    error_text: str,
    title: str | None = None,
    include_system_info: bool = True,
) -> str:
    """生成完整的 bug 报告

    参数:
        error_text: 错误描述
        title: 报告标题（默认 "Bug report"）
        include_system_info: 是否包含系统信息

    返回:
        格式化的报告文本
    """
    lines: list[str] = []

    if title:
        lines.append(f'# {title}')
        lines.append('')

    if include_system_info:
        lines.append('## Environment')
        lines.append('```')
        lines.append(get_system_info())
        lines.append('```')
        lines.append('')

    lines.append('## Description')
    lines.append(error_text)
    lines.append('')

    return '\n'.join(lines)


def open_github_issue(
    error_text: str,
    title: str = 'Bug report',
    repo_url: str = 'https://github.com/clawd-code/claw-code/issues/new',
    confirm: bool = True,
) -> bool:
    """在浏览器中打开 GitHub issue

    参数:
        error_text: 错误描述
        title: issue 标题
        repo_url: 仓库 issue URL
        confirm: 是否要求用户确认

    返回:
        是否成功打开
    """
    # 构建完整的 issue 文本
    issue_text = get_system_info() + '\n\n' + error_text

    params: dict[str, str] = {
        'body': issue_text,
        'title': title,
    }

    issue_url = f'{repo_url}?{urllib.parse.urlencode(params)}'

    if confirm:
        print(f'\n# {title}')
        print(issue_text.strip())
        print()
        print('是否在浏览器中打开预填充的 GitHub issue? (Y/n) ')
        try:
            answer = input().strip().lower()
            if answer and not answer.startswith('y'):
                print('已取消。')
                return False
        except (EOFError, KeyboardInterrupt):
            print()
            return False

    print('正在打开浏览器...')
    try:
        if webbrowser.open(issue_url):
            print(f'浏览器已打开: {issue_url}')
            return True
        else:
            print('无法打开浏览器。请手动访问:')
            print(issue_url)
            return False
    except Exception as e:
        print(f'打开浏览器失败: {e}')
        print(f'请手动访问: {issue_url}')
        return False


# ==================== 环境诊断 ====================

def run_diagnostics() -> dict[str, Any]:
    """运行完整环境诊断

    返回:
        诊断结果字典
    """
    results: dict[str, Any] = {
        'python_version': platform.python_version(),
        'python_implementation': platform.python_implementation(),
        'is_venv': sys.prefix != sys.base_prefix,
        'os': f'{platform.system()} {platform.release()}',
        'architecture': platform.architecture()[0],
        'git_installed': False,
        'git_version': None,
        'dependencies': {},
    }

    # 检查 Git
    try:
        ver = subprocess.check_output(
            ['git', '--version'], stderr=subprocess.DEVNULL
        ).decode().strip()
        results['git_installed'] = True
        results['git_version'] = ver
    except Exception:
        pass

    # 检查依赖
    for mod_name, display_name in [
        ('aider', 'aider'),
        ('litellm', 'litellm'),
        ('tree_sitter', 'tree-sitter'),
        ('tree_sitter_languages', 'tree-sitter-languages'),
        ('networkx', 'networkx'),
        ('diskcache', 'diskcache'),
        ('httpx', 'httpx'),
        ('rich', 'rich'),
        ('prompt_toolkit', 'prompt-toolkit'),
        ('diff_match_patch', 'diff-match-patch'),
        ('watchfiles', 'watchfiles'),
        ('pathspec', 'pathspec'),
        ('pypandoc', 'pypandoc'),
    ]:
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, '__version__', 'installed')
            results['dependencies'][display_name] = {'status': 'ok', 'version': str(ver)}
        except ImportError:
            results['dependencies'][display_name] = {'status': 'missing', 'version': None}

    return results


def format_diagnostics(diag: dict[str, Any]) -> str:
    """格式化诊断结果

    参数:
        diag: run_diagnostics() 返回的诊断字典

    返回:
        格式化的诊断报告
    """
    lines: list[str] = ['== 环境诊断 ==', '']

    lines.append(f'Python: {diag["python_version"]} ({diag["python_implementation"]})')
    lines.append(f'虚拟环境: {"是" if diag["is_venv"] else "否"}')
    lines.append(f'操作系统: {diag["os"]} ({diag["architecture"]})')
    lines.append(f'Git: {diag["git_version"] or "未安装"}')
    lines.append('')

    lines.append('依赖状态:')
    for name, info in diag['dependencies'].items():
        if info['status'] == 'ok':
            lines.append(f'  [OK] {name} ({info["version"]})')
        else:
            lines.append(f'  [MISSING] {name}')

    return '\n'.join(lines)


# 需要在文件顶部导入 Path
from pathlib import Path
