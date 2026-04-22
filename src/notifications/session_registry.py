"""
Session Registry - 会话注册表

从 oh-my-codex-main/src/notifications/session-registry.ts 迁移而来。

功能:
- 跟踪平台消息ID到tmux pane的映射
- 支持回复关联 (reply correlation)
- 使用JSONL格式保证原子写入
- 跨进程锁机制
- 自动清理过期记录 (24小时)

存储位置: ~/.omx/state/reply-session-registry.jsonl (全局, 非工作树本地)
文件权限: 0600 (仅所有者读写)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

# 全局锁 (跨进程使用文件锁, 此处为内存锁辅助)
_REGISTRY_LOCK = Lock()


@dataclass
class SessionMapping:
    """会话映射记录

    将外部平台消息映射到本地会话/tmux pane。
    """
    platform: str  # "discord-bot" | "telegram" | "slack"
    message_id: str  # 平台消息ID
    session_id: str  # 本地会话ID
    tmux_pane_id: str  # tmux pane ID
    tmux_session_name: str  # tmux session name
    event: str  # 触发事件
    created_at: str  # ISO格式时间戳
    project_path: str | None = None  # 项目路径 (可选)


def _get_registry_dir() -> Path:
    """获取注册表目录"""
    home = Path.home()
    return home / '.omx' / 'state'


def _get_registry_path() -> Path:
    """获取注册表文件路径 (JSONL格式)"""
    return _get_registry_dir() / 'reply-session-registry.jsonl'


def _get_lock_path() -> Path:
    """获取锁文件路径"""
    return _get_registry_dir() / 'reply-session-registry.lock'


def _ensure_registry_dir() -> None:
    """确保注册表目录存在 (权限0700)"""
    registry_dir = _get_registry_dir()
    registry_dir.mkdir(parents=True, exist_ok=True)
    # 设置安全权限 (仅所有者读写)
    try:
        os.chmod(registry_dir, 0o700)
    except (OSError, AttributeError):
        pass  # Windows可能不支持


def _acquire_file_lock(lock_path: Path, timeout_ms: int = 2000) -> str | None:
    """获取文件锁 (跨进程同步)

    Args:
        lock_path: 锁文件路径
        timeout_ms: 超时时间 (毫秒)

    Returns:
        锁token (成功) 或 None (失败)
    """
    import uuid

    start_time = time.time()
    token = str(uuid.uuid4())

    while (time.time() - start_time) * 1000 < timeout_ms:
        try:
            # 尝试原子创建锁文件
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, token.encode('utf-8'))
            finally:
                os.close(fd)
            return token
        except FileExistsError:
            # 锁存在, 检查是否过期
            try:
                stat = lock_path.stat()
                age_ms = (time.time() - stat.st_mtime) * 1000
                if age_ms > 10000:  # 10秒过期
                    # 尝试清理僵死锁
                    lock_path.unlink(missing_ok=True)
                    continue
            except (OSError, AttributeError):
                pass
            time.sleep(0.02)  # 20ms重试
        except (OSError, AttributeError):
            # 其他错误, 重试
            time.sleep(0.02)

    return None  # 超时


def _release_file_lock(lock_path: Path, token: str) -> bool:
    """释放文件锁

    Args:
        lock_path: 锁文件路径
        token: 锁token (验证所有权)

    Returns:
        是否成功释放
    """
    try:
        if lock_path.exists():
            # 验证锁token (防止误删他人锁)
            content = lock_path.read_text()
            if content == token:
                lock_path.unlink()
                return True
        return False
    except (OSError, AttributeError):
        return False


def append_mapping(mapping: SessionMapping) -> bool:
    """追加会话映射记录 (原子操作)

    使用JSONL格式, 每行一条记录。
    通过文件锁保证原子性。

    Args:
        mapping: 会话映射对象

    Returns:
        是否成功写入
    """
    _ensure_registry_dir()
    registry_path = _get_registry_path()
    lock_path = _get_lock_path()

    # 获取锁
    token = _acquire_file_lock(lock_path)
    if not token:
        return False

    try:
        # 追加写入 (原子操作)
        line = json.dumps(asdict(mapping), ensure_ascii=False) + '\n'
        with open(registry_path, 'a', encoding='utf-8') as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        return True
    except (OSError, AttributeError, ValueError):
        return False
    finally:
        # 释放锁
        _release_file_lock(lock_path, token)


def find_mapping_by_message_id(
    message_id: str,
    platform: str | None = None,
    max_age_hours: int = 24
) -> SessionMapping | None:
    """根据消息ID查找会话映射

    扫描注册表文件, 查找匹配的最近记录。

    Args:
        message_id: 平台消息ID
        platform: 平台类型 (可选)
        max_age_hours: 最大存活时间 (小时)

    Returns:
        找到的映射对象, 未找到返回None
    """
    registry_path = _get_registry_path()
    if not registry_path.exists():
        return None

    cutoff_ms = (time.time() - max_age_hours * 3600) * 1000

    try:
        with open(registry_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # 检查消息ID匹配
                if data.get('message_id') != message_id:
                    continue

                # 检查平台匹配 (如果指定)
                if platform and data.get('platform') != platform:
                    continue

                # 检查时间戳
                created_at = data.get('created_at', '')
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    ts_ms = dt.timestamp() * 1000
                    if ts_ms < cutoff_ms:
                        continue  # 过期记录
                except (ValueError, AttributeError):
                    continue

                return SessionMapping(**data)

    except (OSError, AttributeError):
        return None

    return None


def find_mapping_by_session_id(
    session_id: str,
    limit: int = 10
) -> list[SessionMapping]:
    """根据会话ID查找映射 (最近N条)

    Args:
        session_id: 会话ID
        limit: 最大返回数量

    Returns:
        映射列表 (按时间倒序)
    """
    registry_path = _get_registry_path()
    if not registry_path.exists():
        return []

    results = []

    try:
        with open(registry_path, encoding='utf-8') as f:
            lines = f.readlines()

        # 倒序遍历 (最近优先)
        for line in reversed(lines):
            if len(results) >= limit:
                break

            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if data.get('session_id') == session_id:
                results.append(SessionMapping(**data))

    except (OSError, AttributeError):
        return []

    return results


def prune_old_entries(max_age_hours: int = 24) -> int:
    """清理过期记录

    重写注册表文件, 只保留最近记录。

    Args:
        max_age_hours: 最大保留时间 (小时)

    Returns:
        清理的记录数量
    """
    registry_path = _get_registry_path()
    if not registry_path.exists():
        return 0

    cutoff_ms = (time.time() - max_age_hours * 3600) * 1000
    kept_lines = []
    pruned_count = 0

    try:
        with open(registry_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    kept_lines.append(line)  # 保留无法解析的行
                    continue

                # 检查时间戳
                created_at = data.get('created_at', '')
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    ts_ms = dt.timestamp() * 1000
                    if ts_ms >= cutoff_ms:
                        kept_lines.append(line)
                    else:
                        pruned_count += 1
                except (ValueError, AttributeError):
                    kept_lines.append(line)  # 无法解析时间, 保留

        # 原子重写
        if pruned_count > 0:
            lock_path = _get_lock_path()
            token = _acquire_file_lock(lock_path)
            if token:
                try:
                    tmp_path = registry_path.with_suffix('.tmp')
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        f.writelines(kept_lines)
                        f.flush()
                        os.fsync(f.fileno())
                    tmp_path.replace(registry_path)
                finally:
                    _release_file_lock(lock_path, token)

    except (OSError, AttributeError):
        pass

    return pruned_count


def get_stats() -> dict[str, Any]:
    """获取注册表统计信息

    Returns:
        统计字典
    """
    registry_path = _get_registry_path()
    if not registry_path.exists():
        return {
            'total_entries': 0,
            'by_platform': {},
            'file_size_bytes': 0,
            'oldest_entry': None,
            'newest_entry': None,
        }

    total = 0
    by_platform: dict[str, int] = {}
    oldest_ts = None
    newest_ts = None

    try:
        with open(registry_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                platform = data.get('platform', 'unknown')
                by_platform[platform] = by_platform.get(platform, 0) + 1

                created_at = data.get('created_at', '')
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    ts = dt.timestamp()
                    if oldest_ts is None or ts < oldest_ts:
                        oldest_ts = ts
                    if newest_ts is None or ts > newest_ts:
                        newest_ts = ts
                except (ValueError, AttributeError):
                    pass

        file_size = registry_path.stat().st_size

    except (OSError, AttributeError):
        return {'total_entries': 0, 'by_platform': {}, 'file_size_bytes': 0}

    return {
        'total_entries': total,
        'by_platform': by_platform,
        'file_size_bytes': file_size,
        'oldest_entry': datetime.fromtimestamp(oldest_ts, tz=timezone.utc).isoformat() if oldest_ts else None,
        'newest_entry': datetime.fromtimestamp(newest_ts, tz=timezone.utc).isoformat() if newest_ts else None,
    }


# ===== 便捷函数 =====

def register_session(
    platform: str,
    message_id: str,
    session_id: str,
    tmux_pane_id: str,
    tmux_session_name: str,
    event: str,
    project_path: str | None = None
) -> bool:
    """快速注册会话映射

    Args:
        platform: 平台名称
        message_id: 消息ID
        session_id: 会话ID
        tmux_pane_id: tmux pane ID
        tmux_session_name: tmux session名
        event: 事件类型
        project_path: 项目路径

    Returns:
        是否注册成功
    """
    mapping = SessionMapping(
        platform=platform,
        message_id=message_id,
        session_id=session_id,
        tmux_pane_id=tmux_pane_id,
        tmux_session_name=tmux_session_name,
        event=event,
        created_at=datetime.now(timezone.utc).isoformat(),
        project_path=project_path,
    )
    return append_mapping(mapping)


def get_session_by_message(
    message_id: str,
    platform: str | None = None
) -> SessionMapping | None:
    """根据消息ID获取会话信息"""
    return find_mapping_by_message_id(message_id, platform)
