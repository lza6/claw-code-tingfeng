from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path
from typing import Any

from .base import BaseTool, ParameterSchema, ToolResult
from .bash_constants import (
    _ALLOWED_WORKDIRS,
    DANGEROUS_PATTERNS_UNIX,
    DANGEROUS_PATTERNS_WINDOWS,
)
from .bash_security import (
    _parse_command_to_list,
    is_shell_command_read_only,
)
from .sandbox.factory import SandboxFactory


class BashTool(BaseTool):
    """安全命令执行工具（跨平台，通过沙箱执行）

    RTK 集成:
    - tee_mode: 失败时保存原始输出 (借鉴 RTK tee.rs)
    - compress_output: 自动压缩输出 (借鉴 RTK 过滤策略)
    - track_tokens: 记录 token 用量
    - isolation: 可选沙箱隔离 (local/docker)
    """

    name = 'BashTool'
    description = '执行安全的 shell 命令（禁止危险操作）'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='command',
            param_type='str',
            required=True,
            description='要执行的命令',
            min_length=1,
            max_length=10000,
        ),
        ParameterSchema(
            name='timeout',
            param_type='int',
            required=False,
            description='命令执行超时时间（秒），默认使用工具配置的超时时间',
            min_value=1,
            max_value=600,
        ),
        ParameterSchema(
            name='memory_limit_mb',
            param_type='int',
            required=False,
            description='（仅 Docker）内存限制（MB）',
            min_value=64,
        ),
    )

    def __init__(
        self,
        workdir: Path | None = None,
        timeout: int = 30,
        max_output_length: int = 50000,
        # RTK-style features
        tee_mode: bool = True,
        compress_output: bool = True,
        track_tokens: bool = True,
        tee_dir: Path | None = None,
        # Isolation
        sandbox_type: str | None = None,
        # God Mode
        bypass_security: bool = False,
    ) -> None:
        self.workdir = workdir or Path.cwd()
        self.timeout = timeout
        self.max_output_length = max_output_length
        # RTK features
        self.tee_mode = tee_mode
        self.compress_output = compress_output
        self.track_tokens = track_tokens
        self.tee_dir = tee_dir or Path('.clawd') / 'tee'
        # Isolation
        self._sandbox_provider = SandboxFactory.create(sandbox_type)
        # God Mode
        self.bypass_security = bypass_security
        # Lazily initialized
        self._compressor: Any = None
        self._tracker: Any = None

    def _get_compressor(self):
        """延迟加载压缩器"""
        if self._compressor is None:
            try:
                from src.core.telemetry.output_compressor import OutputCompressor
                self._compressor = OutputCompressor()
            except ImportError:
                self._compressor = None
        return self._compressor

    def _get_tracker(self):
        """延迟加载追踪器"""
        if self._tracker is None:
            try:
                from src.core.telemetry.token_tracker import TokenTracker
                self._tracker = TokenTracker()
                self._tracker.init()
            except ImportError:
                self._tracker = None
        return self._tracker

    def _compress_if_needed(self, command: str, output: str) -> str:
        """如果启用压缩，对输出进行压缩"""
        if not self.compress_output or not output:
            return output
        compressor = self._get_compressor()
        if compressor is None:
            return output
        try:
            return compressor.compress(command, output)
        except Exception:
            return output

    def _tee_raw_output(self, command: str, raw_output: str, exit_code: int) -> str:
        """RTK 风格的 tee: 命令失败时保存原始输出

        借鉴 RTK 的 tee.rs:
        - 仅在失败时保存 (mode=Failures)
        - 截断大文件 (max 1MB)
        - 自动旋转旧文件 (保留最近 20 个)
        """
        if not self.tee_mode or exit_code == 0:
            return ''

        # 小输出不保存
        if len(raw_output) < 500:
            return ''

        try:
            self.tee_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            slug = re.sub(r'[^a-zA-Z0-9_-]', '_', command[:40])
            filename = f'{ts}_{slug}.log'
            filepath = self.tee_dir / filename

            max_file_size = 1_048_576  # 1MB
            content = raw_output
            if len(content) > max_file_size:
                content = content[:max_file_size] + f'\n\n--- truncated at {max_file_size} bytes ---'

            filepath.write_text(content, encoding='utf-8', errors='replace')
            self._cleanup_old_tee_files()

            # 返回提示 (RTK 的 format_hint)
            home = Path.home()
            try:
                rel = filepath.relative_to(home)
                hint = f'[完整输出已保存到: ~/{rel}]'
            except ValueError:
                hint = f'[完整输出已保存到: {filepath}]'
            return hint
        except Exception:
            return ''

    def _cleanup_old_tee_files(self, max_files: int = 20) -> None:
        """清理旧的 tee 文件 (RTK 风格的文件旋转)"""
        try:
            files = sorted(self.tee_dir.glob('*.log'))
            if len(files) > max_files:
                for f in files[:len(files) - max_files]:
                    f.unlink(missing_ok=True)
        except Exception:
            pass

    def _record_tokens(self, command: str, raw_output: str, compressed_output: str, elapsed_ms: float, success: bool) -> None:
        """记录 token 用量"""
        if not self.track_tokens:
            return
        tracker = self._get_tracker()
        if tracker is None:
            return
        try:
            compressor = self._get_compressor()
            raw_tokens = compressor._estimate_tokens(raw_output) if compressor else len(raw_output) // 3
            compressed_tokens = compressor._estimate_tokens(compressed_output) if compressor else len(compressed_output) // 3

            tracker.record(
                tool_name=self.name,
                raw_tokens=raw_tokens,
                compressed_tokens=compressed_tokens,
                command=command,
                elapsed_ms=elapsed_ms,
                success=success,
                project_path=str(self.workdir),
            )
        except Exception:
            pass

    def validate(self, **kwargs) -> tuple[bool, str]:
        command = kwargs.get('command', '')
        if not command:
            return False, '命令不能为空'

        # 根据平台选择危险命令模式
        patterns = DANGEROUS_PATTERNS_WINDOWS if sys.platform == 'win32' else DANGEROUS_PATTERNS_UNIX

        # 检查危险命令
        if not self.bypass_security:
            for pattern in patterns:
                if re.search(pattern, command, re.IGNORECASE):
                    return False, '命令被拒绝：检测到危险操作模式'

        # --- Project B Enhanced Security ---
        if not self.bypass_security and not is_shell_command_read_only(command):
            return False, f"检测到具有副作用的命令 '{command}'。在正常模式下，出于安全考虑，非只读命令已被禁用。请开启开发者模式 (God Mode) 或使用更安全的命令。"

        # 检查工作目录
        if not self._is_safe_path(self.workdir):
            return False, f'工作目录不在允许范围内: {self.workdir}'

        return True, ''

    def execute(self, **kwargs) -> ToolResult:
        """执行工具 (通过桥接到异步方法)"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 嵌套事件循环风险，在非异步上下文中通常不会发生
                return ToolResult(success=False, output='', error='请使用异步方法 async_execute', exit_code=1)
            return loop.run_until_complete(self.async_execute(**kwargs))
        except Exception as e:
            return ToolResult(success=False, output='', error=f'执行失败: {e}', exit_code=1)

    async def async_execute(self, **kwargs) -> ToolResult:
        """异步执行命令（通过沙箱提供者）"""
        command = kwargs.get('command', '')
        timeout = kwargs.get('timeout', self.timeout)
        memory_limit_mb = kwargs.get('memory_limit_mb')

        is_valid, error_msg = self.validate(command=command)
        if not is_valid:
            return ToolResult(success=False, output='', error=error_msg, exit_code=1)

        try:
            cmd_list = _parse_command_to_list(command)
            if not cmd_list:
                return ToolResult(success=False, output='', error='命令解析失败', exit_code=1)

            # 沙箱执行
            res = await self._sandbox_provider.execute(
                command=cmd_list,
                workdir=self.workdir,
                timeout=timeout,
                memory_limit_mb=memory_limit_mb,
            )

            output = res.stdout
            error_output = res.stderr
            elapsed_ms = res.duration_ms

            # --- RTK: 压缩输出 ---
            raw_output = output
            output = self._compress_if_needed(command, output)

            # --- RTK: 资源监控与限制 (借鉴 Onyx Monitoring) ---
            try:
                from src.core.telemetry.monitoring import get_metrics
                m = get_metrics()
                m.observe_histogram("bash_command_duration_ms", elapsed_ms, labels={"command": command[:20], "success": str(res.is_success).lower()})
                if elapsed_ms > (timeout * 1000 * 0.8):
                    from src.utils import warn
                    warn(f"命令执行接近超时阈值: {command[:50]}... (耗时 {elapsed_ms:.1f}ms, 限制 {timeout}s)")
            except ImportError:
                pass

            # --- RTK: tee 模式 ---
            tee_hint = ''
            if self.tee_mode and not res.is_success:
                tee_hint = self._tee_raw_output(command, raw_output + error_output, res.exit_code)

            # --- RTK: token 追踪 ---
            self._record_tokens(command, raw_output, output, elapsed_ms, res.is_success)

            if len(output) > self.max_output_length:
                output = output[:self.max_output_length] + '\n... [输出已截断]'
            if len(error_output) > self.max_output_length:
                error_output = error_output[:self.max_output_length] + '\n... [输出已截断]'

            if tee_hint:
                error_output = error_output.rstrip() + '\n' + tee_hint if error_output else tee_hint

            return ToolResult(
                success=res.is_success,
                output=output,
                error=error_output,
                exit_code=res.exit_code,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'沙箱执行错误: {e}',
                exit_code=1,
            )

    def _is_safe_path(self, path: Path) -> bool:
        """检查路径是否在允许范围内"""
        if not _ALLOWED_WORKDIRS:
            return True  # 无限制
        resolved = path.resolve()
        return any(resolved.is_relative_to(allowed) for allowed in _ALLOWED_WORKDIRS)

    def __del__(self) -> None:
        """确保资源释放"""
        try:
            if hasattr(self, '_sandbox_provider'):
                self._sandbox_provider.close()
        except Exception:
            pass
