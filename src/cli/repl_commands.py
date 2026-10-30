"""REPL 命令处理器 - 内置命令实现

从 repl.py 拆分出来
包含: /help, /doctor, /tools, /cost, /status 等命令
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from ..utils.colors import (
    bold_cyan,
    dim,
    format_token_count,
    green,
    status_fail,
    status_pass,
    status_warn,
)
from .command_registry import command_registry

BUILTIN_COMMANDS: dict[str, str] = {
    '/help': '显示此帮助信息',
    '/exit': '退出 Clawd Code',
    '/quit': '退出 Clawd Code',
    '/clear': '清除对话历史',
    '/model': '显示/切换当前 LLM 模型',
    '/cost': '显示成本报告',
    '/status': '显示引擎状态',
    '/doctor': '运行环境诊断',
    '/tools': '列出可用工具',
    '/compact': '压缩对话上下文',
    '/version': '显示版本信息',
    '/memory': '显示内存健康报告',
    '/evolve': '触发自动进化审查',
    '/features': '管理实验性功能开关 (God Mode)',
    '/share': '导出当前会话记录',
    '/godpower': '切换开发者模式 (God Mode)',
    '/provider': '切换 API Provider (支持多端点配置)',
    '/internal': '显示/设置内部用户模式 (解锁高级功能)',
    '/override': '管理 GrowthBook 风格的功能覆盖',
    # 新增命令 (借鉴 Aider)
    '/undo': '撤销上一次 AI commit (从 Aider 移植)',
    '/diff': '查看当前未提交的变更 (从 Aider 移植)',
    '/git': '显示 git log / status',
    '/map': '显示代码库 RepoMap (tree-sitter + PageRank)',
    '/read': '读取文件内容',
    '/add': '添加文件到聊天上下文',
    '/drop': '从聊天上下文移除文件',
    '/run': '执行 shell 命令',
    '/report': '显示性能报告',
    '/weak': '显示弱模型路由状态',
}


def _print(text: str = '') -> None:
    """安全打印（处理 Windows GBK 等编码问题）"""
    try:
        print(text)
    except UnicodeEncodeError:
        cleaned = text.encode('ascii', errors='replace').decode('ascii')
        print(cleaned)


def _handle_help() -> None:
    """显示帮助信息（使用命令注册表 - ClawGod 整合）"""
    _print(f'\n  {bold_cyan("Clawd Code")} — AI 编程代理 CLI\n')
    _print(f'  {dim("使用方法:")}')
    _print('    直接输入任务描述，AI 将帮你编程')
    _print('    多行输入：以 \\ 结尾可续行\n')
    _print(f'  {dim("内置命令:")}')

    help_text = command_registry.get_help_text()
    if help_text:
        _print(help_text)
    else:
        for cmd, desc in BUILTIN_COMMANDS.items():
            _print(f'    {green(cmd):30s} {desc}')

    _print(f'\n  {dim("快捷键:")}')
    _print(f'    {green("Ctrl+C"):30s} 中止当前任务')
    _print(f'    {green("Ctrl+D"):30s} 退出')
    _print()


def _handle_version() -> None:
    """显示版本信息"""
    from .banner import _get_model_info, _get_version
    version = _get_version()
    provider, model = _get_model_info()
    _print(f'  Clawd Code v{version}')
    _print(f'  LLM: {provider} / {model}')
    _print(f'  Python: {sys.version.split()[0]}')


def collect_doctor_report() -> dict[str, Any]:
    """收集环境诊断（结构化）—— `clawd doctor --json` 与终端渲染共用同一份数据

    以前 `_handle_doctor()` 是"边查边打印"，机器读不到；现在先收集再渲染，
    单一来源，避免 JSON 与人读两份逻辑漂移。

    **密钥只报"已设置"，不回显任何片段**：JSON 比人读更容易被采集/上报。
    """
    checks: list[dict[str, Any]] = []

    def add(section: str, level: str, text: str) -> None:
        checks.append({'section': section, 'level': level, 'text': text})

    # ---------- 环境诊断 ----------
    py_ver = sys.version_info
    if py_ver >= (3, 10):
        add('env', 'pass', f'Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}')
    else:
        add('env', 'fail', f'Python {py_ver.major}.{py_ver.minor} (需要 >=3.10)')

    for dep in ['openai', 'anthropic', 'websockets', 'tiktoken', 'httpx']:
        try:
            mod = __import__(dep)
            ver = getattr(mod, '__version__', getattr(mod, 'VERSION', '已安装'))
            add('env', 'pass', f'{dep} {ver}')
        except ImportError:
            optional = dep in ('tiktoken', 'httpx')
            add('env', 'warn' if optional else 'fail',
                f'{dep} 未安装' + ('（可选）' if optional else ''))

    provider = os.environ.get('LLM_PROVIDER', '')
    if provider:
        add('env', 'pass', f'LLM_PROVIDER={provider}')
    else:
        add('env', 'warn', 'LLM_PROVIDER 未设置 (默认 openai)')

    key_map = {
        'openai': 'OPENAI_API_KEY',
        'anthropic': 'ANTHROPIC_API_KEY',
        'google': 'GOOGLE_API_KEY',
        'groq': 'GROQ_API_KEY',
        'together': 'TOGETHER_API_KEY',
        'mistral': 'MISTRAL_API_KEY',
        'deepseek': 'DEEPSEEK_API_KEY',
    }
    key_found = False
    for _p, k in key_map.items():
        if os.environ.get(k, ''):
            add('env', 'pass', f'{k}=已设置（不回显）')
            key_found = True
    if not key_found:
        add('env', 'fail', '未发现任何 API Key')

    workdir = Path(os.environ.get('WORK_DIR', os.getcwd()))
    if workdir.exists():
        add('env', 'pass', f'工作目录: {workdir}')
    else:
        add('env', 'fail', f'工作目录不存在: {workdir}')

    # ---------- 框架一致性 ----------
    try:
        import re

        pyproject = workdir / 'pyproject.toml'
        readme = workdir / 'README.md'
        py_version = ''
        if pyproject.exists():
            match = re.search(r'version\s*=\s*"([^"]+)"', pyproject.read_text(encoding='utf-8'))
            if match:
                py_version = match.group(1)
        rd_version = ''
        if readme.exists():
            match = re.search(
                r'当前版本\**\s*[:：]\s*\**\s*v?([\d\.]+)', readme.read_text(encoding='utf-8')
            )
            if match:
                rd_version = match.group(1)
        if py_version and rd_version:
            if py_version == rd_version:
                add('consistency', 'pass', f'版本一致性: {py_version}')
            else:
                add('consistency', 'fail',
                    f'版本不匹配: pyproject({py_version}) vs README({rd_version})')
        else:
            add('consistency', 'warn', '无法提取完整版本信息进行比对')
    except Exception as e:  # noqa: BLE001 — 诊断本身不能因为检查项异常而中断
        add('consistency', 'warn', f'框架一致性检查过程中出现异常: {e}')

    # ---------- 能力状态 ----------
    try:
        import importlib.util

        def _has(module: str) -> bool:
            return importlib.util.find_spec(module) is not None

        rag_on = os.environ.get('CLAWD_ENABLE_RAG', '').lower() in ('1', 'true', 'yes')
        if _has('src.rag.text_indexer'):
            if rag_on:
                add('capabilities', 'pass', 'RAG 索引: 已启用 (CLAWD_ENABLE_RAG=1)')
            else:
                add('capabilities', 'warn', 'RAG 索引: 默认关闭 (设置 CLAWD_ENABLE_RAG=1 启用)')
        else:
            add('capabilities', 'fail', 'RAG 索引: 模块不可导入')

        if _has('src.brain.world_model'):
            add('capabilities', 'pass', 'World Model: 可用 (Agent 启动时后台初始化)')
        else:
            add('capabilities', 'warn', 'World Model: 模块不可导入')

        if _has('src.server.websocket_server'):
            add('capabilities', 'pass', 'WebSocket 服务端: 模块可用')
        else:
            add('capabilities', 'warn', 'WebSocket 服务端: 模块不可导入')
    except Exception as e:  # noqa: BLE001
        add('capabilities', 'warn', f'能力状态检查失败: {e}')

    failed = sum(1 for c in checks if c['level'] == 'fail')
    return {
        'ready': failed == 0,
        'checks': checks,
        'count': len(checks),
        'failed': failed,
    }


_SECTION_TITLES = {
    'env': '环境诊断',
    'consistency': '框架一致性',
    'capabilities': '能力状态（默认是否启用）',
}


def _handle_doctor() -> None:
    """运行环境诊断（终端渲染；`--json` 走 `collect_doctor_report()`，同一份数据）"""
    report = collect_doctor_report()
    marks = {'pass': status_pass(), 'warn': status_warn(), 'fail': status_fail()}
    current = None
    for check in report['checks']:
        section = check['section']
        if section != current:
            _print(f'\n  {bold_cyan(_SECTION_TITLES.get(section, section))}\n')
            current = section
        _print(f"  {marks[check['level']]} {dim(check['text'])}")
    _print()


def _handle_tools(engine: Any) -> None:
    """列出可用工具"""
    tools = engine.get_available_tools()
    _print(f'\n  {bold_cyan("可用工具")} ({len(tools)} 个)\n')
    for name in sorted(tools):
        tool = tools[name]
        desc = getattr(tool, 'description', getattr(tool, 'name', name))
        _print(f'  {green(name):30s} {dim(str(desc)[:60])}')
    _print()


def _handle_cost(engine: Any) -> None:
    """显示成本报告"""
    report = engine.get_cost_report()
    if report:
        # 如果是 CostEstimator 生成的报告，它已经包含了详细的 Token 统计 (v0.65.0)
        _print(f'\n{report}')
    else:
        _print(f'\n  {dim("暂无成本数据")}\n')


def _handle_status(engine: Any) -> None:
    """显示引擎状态"""
    _print(f'\n  {bold_cyan("引擎状态")}\n')
    _print(f'  运行中: {green("是") if engine.is_running else dim("否")}')
    tools = engine.get_available_tools()
    _print(f'  工具数: {len(tools)}')

    summary = engine.get_cost_summary()
    if summary:
        _print(f'  总调用: {summary.get("total_calls", 0)} 次')
        _print(f'  总成本: ${summary.get("total_cost", 0):.4f}')
        _print(f'  总Token: {format_token_count(summary.get("total_tokens", 0))}')

        # 新增: 缓存与推理 Token 详情 (v0.65.0)
        cache_read = summary.get("total_cache_read_tokens", 0)
        cache_write = summary.get("total_cache_write_tokens", 0)
        reasoning = summary.get("total_reasoning_tokens", 0)

        if cache_read > 0 or cache_write > 0 or reasoning > 0:
            parts = []
            if cache_read > 0:
                parts.append(f'缓存读: {format_token_count(cache_read)}')
            if cache_write > 0:
                parts.append(f'缓存写: {format_token_count(cache_write)}')
            if reasoning > 0:
                parts.append(f'推理: {format_token_count(reasoning)}')
            _print(f'  详情: {dim(" / ".join(parts))}')

    perf_summary = engine.get_perf_summary()
    if perf_summary:
        _print(f'\n  {perf_summary}')
    _print()
