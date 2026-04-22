"""
Idle Notification Cooldown - 空闲通知冷却

从 oh-my-codex-main/src/notifications/idle-cooldown.ts 迁移而来。

功能:
- 防止用户被session-idle通知淹没
- 通过强制最小间隔来限制通知频率
- 支持会话范围的状态文件
- 环境变量 + 配置文件双重控制
- 值为0时完全禁用冷却

配置键: notifications.idleCooldownSeconds in ~/.omx/.omx-config.json
环境变量: OMX_IDLE_COOLDOWN_SECONDS (覆盖配置)
状态文件: .omx/state/idle-notif-cooldown.json
           (当sessionId可用时为会话作用域)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# ===== 常量 =====
DEFAULT_COOLDOWN_SECONDS = 60
SESSION_ID_SAFE_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,255}$')


def get_idle_notification_cooldown_seconds() -> int:
    """获取空闲通知冷却时间（秒）
    
    解析顺序:
      1. OMX_IDLE_COOLDOWN_SECONDS 环境变量
      2. notifications.idleCooldownSeconds in ~/.omx/.omx-config.json
      3. 默认: 60 秒
      
    Returns:
        冷却时间（秒），0表示禁用冷却
    """
    # 1. 环境变量覆盖
    env_val = os.environ.get('OMX_IDLE_COOLDOWN_SECONDS')
    if env_val is not None:
        try:
            parsed = int(env_val)
            if parsed >= 0:
                return parsed
        except (ValueError, TypeError):
            pass  # 无效值，回退到下一个来源

    # 2. 配置文件
    try:
        from .config import load_notification_config
        config = load_notification_config()
        if config and hasattr(config, 'idleCooldownSeconds'):
            val = config.idleCooldownSeconds
            if isinstance(val, (int, float)) and val >= 0:
                return int(val)
    except (ImportError, AttributeError, Exception):
        pass  # 配置加载失败，回退到默认值

    # 3. 默认值
    return DEFAULT_COOLDOWN_SECONDS


def get_cooldown_state_path(state_dir: str, session_id: str | None = None) -> Path:
    """解析冷却状态文件路径
    
    当提供且安全的sessionId时使用会话作用域路径。
    
    Args:
        state_dir: 状态目录路径
        session_id: 可选的会话ID
        
    Returns:
        冷却状态文件的Path对象
    """
    state_path = Path(state_dir)
    if session_id and SESSION_ID_SAFE_PATTERN.match(session_id):
        return state_path / 'sessions' / session_id / 'idle-notif-cooldown.json'
    return state_path / 'idle-notif-cooldown.json'


def should_send_idle_notification(state_dir: str, session_id: str | None = None) -> bool:
    """检查是否应该发送空闲通知
    
    如果冷却时间已过或被禁用则返回True（应该发送）。
    如果距离上次发送时间太近则返回False（应该抑制）。
    
    Args:
        state_dir: 状态目录路径
        session_id: 可选的会话ID（用于会话作用域冷却）
        
    Returns:
        True如果应该发送通知，False如果应该抑制
    """
    cooldown_secs = get_idle_notification_cooldown_seconds()

    # 冷却时间为0表示禁用 — 总是发送
    if cooldown_secs == 0:
        return True

    cooldown_path = get_cooldown_state_path(state_dir, session_id)

    try:
        if not cooldown_path.exists():
            return True  # 没有历史记录，允许发送

        # 读取上次发送时间
        with open(cooldown_path, encoding='utf-8') as f:
            data = json.load(f)

        last_sent_at = data.get('lastSentAt')
        if not last_sent_at or not isinstance(last_sent_at, str):
            return True  # 无效记录，允许发送

        # 解析时间戳
        from datetime import datetime
        try:
            last_sent_ms = datetime.fromisoformat(last_sent_at.replace('Z', '+00:00')).timestamp() * 1000
        except (ValueError, AttributeError):
            return True  # 解析失败，允许发送

        # 计算经过时间
        import time
        elapsed_secs = (time.time() * 1000 - last_sent_ms) / 1000

        # 如果经过时间小于冷却时间，则抑制通知
        return elapsed_secs >= cooldown_secs

    except (OSError, json.JSONDecodeError, Exception):
        # 读取/解析错误 — 视为无冷却文件，允许发送
        return True


def record_idle_notification_sent(state_dir: str, session_id: str | None = None) -> None:
    """记录空闲通知已发送的时间戳
    
    在成功发送通知后调用此函数以启动冷却。
    
    Args:
        state_dir: 状态目录路径
        session_id: 可选的会话ID（用于会话作用域冷却）
    """
    cooldown_path = get_cooldown_state_path(state_dir, session_id)

    try:
        # 确保目录存在
        cooldown_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入当前时间戳
        from datetime import datetime
        timestamp = datetime.now().isoformat()

        with open(cooldown_path, 'w', encoding='utf-8') as f:
            json.dump({'lastSentAt': timestamp}, f, indent=2)
    except (OSError, Exception):
        # 忽略写入错误 — 尽力而为
        pass


# ===== 便捷函数 =====

def get_effective_cooldown_seconds() -> int:
    """获取有效的冷却时间（用于日志和显示）
    
    Returns:
        有效的冷却时间（秒）
    """
    return get_idle_notification_cooldown_seconds()


def is_cooldown_enabled() -> bool:
    """检查冷却机制是否启用
    
    Returns:
        True如果冷却时间 > 0，False如果为0（禁用）
    """
    return get_idle_notification_cooldown_seconds() > 0
