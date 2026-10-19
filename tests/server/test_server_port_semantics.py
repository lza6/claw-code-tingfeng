"""WebSocket 服务端端口语义测试（P1-7）。

`port=0` 是合法值（由操作系统分配随机端口），不能与"未提供"混为一谈。
"""
from __future__ import annotations

from src.server import create_server


def test_explicit_zero_port_is_preserved():
    srv = create_server(host='127.0.0.1', port=0, token='t')
    assert srv.port == 0


def test_explicit_port_is_preserved():
    srv = create_server(host='127.0.0.1', port=8765, token='t')
    assert srv.port == 8765


def test_none_port_falls_back_to_settings():
    srv = create_server(host='127.0.0.1', port=None, token='t')
    assert isinstance(srv.port, int)
    assert srv.port >= 0
