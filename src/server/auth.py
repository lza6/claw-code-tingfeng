"""WebSocket 服务端令牌认证模块

为 WebSocket 连接提供基于令牌的认证机制，支持多会话鉴权与状态追踪。
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from ..utils import get_logger

if TYPE_CHECKING:
    from websockets import ServerProtocol


class AuthManager:
    """基于令牌的 WebSocket 连接认证管理器。

    职责:
        - 管理服务级认证令牌（来自环境变量或显式注入）
        - 追踪已认证的连接集合
        - 提供认证与鉴权查询接口
    """

    def __init__(self, token: str | None = None) -> None:
        """初始化认证管理器。

        参数:
            token: 认证令牌。若为 None，则从环境变量 ``AGENT_SERVER_TOKEN`` 读取。
        """
        self.logger = get_logger('server.auth')
        self.token = token or os.environ.get('AGENT_SERVER_TOKEN', '')
        # 已认证的 WebSocket 连接集合
        self._authenticated: set[ServerProtocol] = set()
        # 连接认证时间戳映射
        self._auth_times: dict[ServerProtocol, float] = {}

        if not self.token:
            self.logger.warn('AGENT_SERVER_TOKEN 未设置，所有认证请求均将失败')

    # ------------------------------------------------------------------
    # 核心认证逻辑
    # ------------------------------------------------------------------

    async def authenticate(self, ws: ServerProtocol, token: str) -> bool:
        """验证客户端提供的令牌。

        参数:
            ws: WebSocket 连接对象。
            token: 客户端提供的认证令牌。

        返回:
            认证成功返回 True，否则返回 False。
        """
        if not self.token:
            self.logger.warn(
                '认证失败：服务端令牌未配置',
                client=ws.remote_address,
            )
            return False

        if constant_time_compare(token, self.token):
            self._authenticated.add(ws)
            self._auth_times[ws] = time.time()
            self.logger.info(
                '认证成功',
                client=ws.remote_address,
            )
            return True

        self.logger.warn(
            '认证失败：令牌不匹配',
            client=ws.remote_address,
        )
        return False

    def is_authenticated(self, ws: ServerProtocol) -> bool:
        """检查连接是否已通过认证。

        参数:
            ws: WebSocket 连接对象。

        返回:
            已认证返回 True，否则返回 False。
        """
        return ws in self._authenticated

    def authenticated_since(self, ws: ServerProtocol) -> float | None:
        """获取连接的认证时间戳。

        参数:
            ws: WebSocket 连接对象。

        返回:
            认证时间戳（秒级 Unix 时间），若未认证则返回 None。
        """
        return self._auth_times.get(ws)

    # ------------------------------------------------------------------
    # 连接生命周期管理
    # ------------------------------------------------------------------

    def register(self, ws: ServerProtocol) -> None:
        """注册一个新连接（默认未认证状态）。

        参数:
            ws: WebSocket 连接对象。
        """
        # 注册时不加入 _authenticated，需等待 authenticate() 调用
        self.logger.debug('新连接已注册', client=ws.remote_address)

    def unregister(self, ws: ServerProtocol) -> None:
        """注销连接，清除其认证状态。

        参数:
            ws: WebSocket 连接对象。
        """
        self._authenticated.discard(ws)
        self._auth_times.pop(ws, None)
        self.logger.debug('连接已注销', client=ws.remote_address)

    @property
    def authenticated_count(self) -> int:
        """返回当前已认证的连接数量。"""
        return len(self._authenticated)


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def constant_time_compare(a: str, b: str) -> bool:
    """常量时间字符串比较，防止时序攻击。

    参数:
        a: 第一个字符串。
        b: 第二个字符串。

    返回:
        两字符串相等返回 True，否则返回 False。
    """
    import hmac

    return hmac.compare_digest(a.encode('utf-8'), b.encode('utf-8'))
