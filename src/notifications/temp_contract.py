"""
Temporary Contract Management - 临时合同管理

从 oh-my-codex-main/src/notifications/temp-contract.ts 迁移而来。

功能:
- 管理临时模式状态
- 会话生命周期绑定
- 自动清理过期状态
- 支持跨进程状态共享
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any

# 全局锁 (内存锁辅助文件锁)
_TEMP_CONTRACT_LOCK = Lock()


@dataclass
class TempContractState:
    """临时合同状态
    
    用于跟踪临时模式会话的状态信息。
    """
    session_id: str  # 会话ID
    mode: str        # 模式名称 (如: team, ralph, autopilot等)
    started_at: str  # 开始时间戳 (ISO格式)
    expires_at: str  # 过期时间戳 (ISO格式)
    data: dict[str, Any]  # 自定义数据

    @property
    def is_expired(self) -> bool:
        """检查是否已过期"""
        try:
            from datetime import datetime
            expires_dt = datetime.fromisoformat(self.expires_at.replace('Z', '+00:00'))
            now_dt = datetime.now()
            return now_dt > expires_dt
        except (ValueError, AttributeError):
            return True  # 解析失败视为过期


def _get_temp_contract_dir() -> Path:
    """获取临时合同目录"""
    home = Path.home()
    return home / '.omx' / 'state' / 'temp-contracts'


def _get_contract_path(session_id: str) -> Path:
    """获取特定会话的合同文件路径"""
    # 安全的会话ID用于文件名
    safe_session_id = "".join(c for c in session_id if c.isalnum() or c in '-_')
    if not safe_session_id:
        safe_session_id = "unknown"
    return _get_temp_contract_dir() / f"{safe_session_id}.json"


def _ensure_temp_contract_dir() -> None:
    """确保临时合同目录存在 (权限0700)"""
    temp_dir = _get_temp_contract_dir()
    temp_dir.mkdir(parents=True, exist_ok=True)
    # 设置安全权限 (仅所有者读写)
    try:
        os.chmod(temp_dir, 0o700)
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


def create_temp_contract(
    session_id: str,
    mode: str,
    duration_seconds: int = 3600,
    initial_data: dict[str, Any] | None = None
) -> bool:
    """创建临时合同

    Args:
        session_id: 会话ID
        mode: 模式名称
        duration_seconds: 有效期（秒），默认1小时
        initial_data: 初始数据字典

    Returns:
        是否创建成功
    """
    _ensure_temp_contract_dir()
    contract_path = _get_contract_path(session_id)
    lock_path = contract_path.with_suffix('.lock')

    # 生成时间戳
    from datetime import datetime, timedelta
    now = datetime.now()
    expires = now + timedelta(seconds=duration_seconds)

    state = TempContractState(
        session_id=session_id,
        mode=mode,
        started_at=now.isoformat(),
        expires_at=expires.isoformat(),
        data=initial_data or {},
    )

    # 获取锁
    token = _acquire_file_lock(lock_path)
    if not token:
        return False

    try:
        # 原子写入
        tmp_path = contract_path.with_suffix('.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(state), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(contract_path)
        return True
    except (OSError, AttributeError, ValueError):
        return False
    finally:
        # 释放锁
        _release_file_lock(lock_path, token)


def get_temp_contract(session_id: str) -> TempContractState | None:
    """获取临时合同状态

    Args:
        session_id: 会话ID

    Returns:
        TempContractState对象，如果不存在或已过期则返回None
    """
    contract_path = _get_contract_path(session_id)
    if not contract_path.exists():
        return None

    try:
        with open(contract_path, encoding='utf-8') as f:
            data = json.load(f)

        state = TempContractState(**data)

        # 检查是否过期
        if state.is_expired:
            # 自动清理过期合同
            delete_temp_contract(session_id)
            return None

        return state
    except (OSError, json.JSONDecodeError, TypeError):
        # 损坏的文件，删除它
        delete_temp_contract(session_id)
        return None


def update_temp_contract_data(
    session_id: str,
    data_updates: dict[str, Any]
) -> bool:
    """更新临时合同数据

    Args:
        session_id: 会话ID
        data_updates: 要更新的数据字典

    Returns:
        是否更新成功
    """
    contract_path = _get_contract_path(session_id)
    if not contract_path.exists():
        return False

    lock_path = contract_path.with_suffix('.lock')

    # 获取锁
    token = _acquire_file_lock(lock_path)
    if not token:
        return False

    try:
        # 读取现有状态
        with open(contract_path, encoding='utf-8') as f:
            existing_data = json.load(f)

        # 更新数据
        existing_data['data'].update(data_updates)

        # 原子写回
        tmp_path = contract_path.with_suffix('.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(contract_path)
        return True
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    finally:
        # 释放锁
        _release_file_lock(lock_path, token)


def delete_temp_contract(session_id: str) -> bool:
    """删除临时合同

    Args:
        session_id: 会话ID

    Returns:
        是否删除成功（如果不存在也返回True）
    """
    contract_path = _get_contract_path(session_id)
    if not contract_path.exists():
        return True  # 已经不存在，视为成功

    lock_path = contract_path.with_suffix('.lock')

    # 获取锁
    token = _acquire_file_lock(lock_path)
    if not token:
        return False

    try:
        contract_path.unlink()
        return True
    except OSError:
        return False
    finally:
        # 释放锁
        _release_file_lock(lock_path, token)


def cleanup_expired_contracts() -> int:
    """清理所有过期的临时合同

    Returns:
        清理的合同数量
    """
    temp_dir = _get_temp_contract_dir()
    if not temp_dir.exists():
        return 0

    cleaned_count = 0
    try:
        for contract_file in temp_dir.glob("*.json"):
            # 提取会话ID（简化处理）
            session_id = contract_file.stem
            contract = get_temp_contract(session_id)
            if contract is None:  # 已过期或不存在
                # 尝试删除
                lock_path = contract_file.with_suffix('.lock')
                token = _acquire_file_lock(lock_path)
                if token:
                    try:
                        if contract_file.exists():
                            contract_file.unlink()
                            cleaned_count += 1
                    except OSError:
                        pass
                    finally:
                        _release_file_lock(lock_path, token)
    except OSError:
        pass

    return cleaned_count


def list_active_contracts() -> list[TempContractState]:
    """列出所有活跃的临时合同

    Returns:
        活跃的TempContractState列表
    """
    temp_dir = _get_temp_contract_dir()
    if not temp_dir.exists():
        return []

    active_contracts = []
    try:
        for contract_file in temp_dir.glob("*.json"):
            session_id = contract_file.stem
            contract = get_temp_contract(session_id)
            if contract is not None:
                active_contracts.append(contract)
    except OSError:
        pass

    return active_contracts


# ===== 便捷函数 =====

def is_temp_contract_active(session_id: str, mode: str | None = None) -> bool:
    """检查临时合同是否活跃

    Args:
        session_id: 会话ID
        mode: 可选的模式过滤

    Returns:
        True如果合同存在、未过期且(如果指定)模式匹配
    """
    contract = get_temp_contract(session_id)
    if contract is None:
        return False
    if mode and contract.mode != mode:
        return False
    return True


def get_contract_stats() -> dict[str, Any]:
    """获取临时合同统计信息

    Returns:
        统计字典
    """
    temp_dir = _get_temp_contract_dir()
    if not temp_dir.exists():
        return {
            'total_contracts': 0,
            'active_contracts': 0,
            'expired_contracts': 0,
            'by_mode': {},
            'disk_usage_bytes': 0,
        }

    total = 0
    active = 0
    expired = 0
    by_mode: dict[str, int] = {}
    disk_usage = 0

    try:
        for contract_file in temp_dir.glob("*.json"):
            total += 1
            try:
                stat = contract_file.stat()
                disk_usage += stat.st_size
            except OSError:
                pass

            session_id = contract_file.stem
            contract = get_temp_contract(session_id)
            if contract is None:
                expired += 1
            else:
                active += 1
                mode = contract.mode
                by_mode[mode] = by_mode.get(mode, 0) + 1
    except OSError:
        pass

    return {
        'total_contracts': total,
        'active_contracts': active,
        'expired_contracts': expired,
        'by_mode': by_mode,
        'disk_usage_bytes': disk_usage,
    }
