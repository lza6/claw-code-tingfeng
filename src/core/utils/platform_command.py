"""Platform Command Utilities

Provides cross-platform command execution with proper error handling and
path resolution, inspired by oh-my-codex's platform-command.ts.
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SpawnErrorKind(Enum):
    """Types of errors that can occur when spawning processes."""
    MISSING = "missing"      # Command not found
    BLOCKED = "blocked"      # Command found but not executable
    ERROR = "error"          # Command failed during execution


@dataclass
class PlatformCommandSpec:
    """Specification for a platform command."""
    command: str
    args: list[str]
    options: dict[str, Any] = None

    def __post_init__(self):
        if self.options is None:
            self.options = {}


@dataclass
class ProbedPlatformCommand:
    """A probed platform command with resolved path."""
    spec: PlatformCommandSpec
    resolved_path: str


def classify_spawn_error(error: Exception | None) -> SpawnErrorKind | None:
    """Classify an exception from subprocess into a SpawnErrorKind.
    
    Args:
        error: Exception from subprocess execution
        
    Returns:
        SpawnErrorKind or None if no error
    """
    if error is None:
        return None

    if isinstance(error, FileNotFoundError):
        return SpawnErrorKind.MISSING
    elif isinstance(error, PermissionError):
        return SpawnErrorKind.BLOCKED
    else:
        return SpawnErrorKind.ERROR


def resolve_command_path_for_platform(
    command: str,
    env: dict[str, str] | None = None,
    path_env: str | None = None,
) -> str | None:
    """Resolve the full path to a command executable.
    
    Args:
        command: Command name or path
        env: Environment variables (defaults to os.environ)
        path_env: PATH environment variable to search
        
    Returns:
        Full path to executable or None if not found
    """
    env = env or os.environ
    path_env = path_env or env.get("PATH", "")

    # If command contains path separators, check if it's executable
    if os.sep in command or (hasattr(os, 'altsep') and os.altsep in command):
        if os.path.isfile(command) and os.access(command, os.X_OK):
            return command
        return None

    # Search in PATH
    for path_dir in path_env.split(os.pathsep):
        if not path_dir:
            continue
        full_path = os.path.join(path_dir, command)
        if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
            return full_path

    return None


def build_platform_command_spec(
    command: str,
    args: str | list[str],
    options: dict[str, Any] | None = None,
) -> PlatformCommandSpec:
    """Build a PlatformCommandSpec from command and arguments.
    
    Args:
        command: Command to execute
        args: Arguments (string or list)
        options: Additional options
        
    Returns:
        PlatformCommandSpec
    """
    if isinstance(args, str):
        # Simple split - for complex parsing, use shlex.split
        args_list = args.split()
    else:
        args_list = list(args)

    return PlatformCommandSpec(
        command=command,
        args=args_list,
        options=options or {},
    )


def spawn_platform_command_sync(
    command: str,
    args: str | list[str],
    options: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float | None = None,
    capture_output: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Synchronously spawn a platform command with proper error handling.
    
    Args:
        command: Command to execute
        args: Arguments (string or list)
        options: Command options (for logging, etc.)
        env: Environment variables
        cwd: Working directory
        timeout: Timeout in seconds
        capture_output: Whether to capture stdout/stderr
        check: Whether to raise exception on non-zero exit
        
    Returns:
        CompletedProcess instance
        
    Raises:
        subprocess.TimeoutExpired: If timeout exceeded
        subprocess.CalledProcessError: If check=True and non-zero exit
    """
    env = env or os.environ.copy()
    cwd = cwd or os.getcwd()

    spec = build_platform_command_spec(command, args, options)

    logger.debug(f"Executing command: {command} {' '.join(spec.args)}")

    try:
        result = subprocess.run(
            [command] + spec.args,
            env=env,
            cwd=cwd,
            timeout=timeout,
            capture_output=capture_output,
            text=True,
            check=check,
        )
        return result
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {timeout}s: {command}")
        raise
    except Exception as e:
        error_kind = classify_spawn_error(e)
        logger.error(f"Failed to execute command {command}: {error_kind} - {e}")
        raise


async def spawn_platform_command_async(
    command: str,
    args: str | list[str],
    options: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Asynchronously spawn a platform command.
    
    Args:
        command: Command to execute
        args: Arguments (string or list)
        options: Command options
        env: Environment variables
        cwd: Working directory
        timeout: Timeout in seconds
        
    Returns:
        CompletedProcess instance
    """
    import asyncio

    env = env or os.environ.copy()
    cwd = cwd or os.getcwd()

    spec = build_platform_command_spec(command, args, options)

    logger.debug(f"Executing async command: {command} {' '.join(spec.args)}")

    try:
        process = await asyncio.create_subprocess_exec(
            command,
            *spec.args,
            env=env,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE if options.get('capture_output', True) else None,
            stderr=asyncio.subprocess.PIPE if options.get('capture_output', True) else None,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            returncode = process.returncode

            result = subprocess.CompletedProcess(
                args=[command] + spec.args,
                returncode=returncode,
                stdout=stdout.decode() if stdout else None,
                stderr=stderr.decode() if stderr else None,
            )

            if options.get('check', False) and returncode != 0:
                raise subprocess.CalledProcessError(returncode, result.args, result.stdout, result.stderr)

            return result
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise subprocess.TimeoutExpired([command] + spec.args, timeout)

    except Exception as e:
        error_kind = classify_spawn_error(e)
        logger.error(f"Failed to execute async command {command}: {error_kind} - {e}")
        raise


def probe_platform_command(
    command: str,
    env: dict[str, str] | None = None,
    path_env: str | None = None,
) -> ProbedPlatformCommand | None:
    """Probe for a platform command and return resolved path.
    
    Args:
        command: Command to probe
        env: Environment variables
        path_env: PATH to search
        
    Returns:
        ProbedPlatformCommand if found, None otherwise
    """
    resolved_path = resolve_command_path_for_platform(command, env, path_env)
    if resolved_path is None:
        return None

    spec = build_platform_command_spec(command, [])
    return ProbedPlatformCommand(spec=spec, resolved_path=resolved_path)


def which(command: str) -> str | None:
    """Python implementation of 'which' command.
    
    Args:
        command: Command to find
        
    Returns:
        Full path to command or None if not found
    """
    return resolve_command_path_for_platform(command)


def is_command_available(command: str) -> bool:
    """Check if a command is available in PATH.
    
    Args:
        command: Command to check
        
    Returns:
        True if command is available, False otherwise
    """
    return resolve_command_path_for_platform(command) is not None


# Convenience functions for common commands
def run_command(
    command: str,
    args: str | list[str] = [],
    **kwargs
) -> subprocess.CompletedProcess:
    """Run a command and return CompletedProcess.
    
    Args:
        command: Command to run
        args: Command arguments
        **kwargs: Additional arguments to spawn_platform_command_sync
        
    Returns:
        CompletedProcess
    """
    return spawn_platform_command_sync(command, args, **kwargs)


def run_command_check(
    command: str,
    args: str | list[str] = [],
    **kwargs
) -> subprocess.CompletedProcess:
    """Run a command and raise on non-zero exit.
    
    Args:
        command: Command to run
        args: Command arguments
        **kwargs: Additional arguments to spawn_platform_command_sync
        
    Returns:
        CompletedProcess
    """
    kwargs['check'] = True
    return spawn_platform_command_sync(command, args, **kwargs)

