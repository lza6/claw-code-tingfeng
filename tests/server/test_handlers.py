"""服务器处理器测试 - 覆盖 src/server/handlers.py"""

import pytest
from src.server.handlers import (
    build_response,
    build_error,
)


class TestBuildResponse:
    def test_build_response_basic(self):
        result = build_response(msg_id=1, data={"result": "ok"})
        assert "id" in result
        assert "result" in result or "data" in result

    def test_build_response_no_id(self):
        result = build_response(msg_id=None, data={"result": "ok"})
        assert "id" in result


class TestBuildError:
    def test_build_error_basic(self):
        result = build_error(msg_id=1, code="-32600", message="Invalid params")
        assert "id" in result