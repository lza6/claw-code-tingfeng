"""全局 pytest 配置与共享 fixture。

背景:
    本仓库此前**没有 conftest.py**，所有测试各自 setUp，导致：
    1. 事件总线等全局单例在测试间相互污染（表现为"单独跑通过、全量跑报错"）；
    2. 每个测试重复做环境初始化，拖慢整体运行；
    3. 自定义 mark 未注册，产生大量 PytestUnknownMarkWarning。

设计原则:
    fixture 一律**可选加入**，不做 autouse 全局副作用 —— 避免为了治一个
    问题而改变几百个既有测试的行为假设。
"""
from __future__ import annotations

import pytest


@pytest.fixture
def clean_event_bus():
    """提供干净的全局事件总线，用完自动清理。

    适用于断言"某事件是否被发布"的测试：订阅前先清空，避免受同进程内
    其它测试遗留的订阅者影响。
    """
    from src.core.events import get_event_bus

    bus = get_event_bus()
    bus.clear()
    yield bus
    bus.clear()


@pytest.fixture
def isolated_workdir(tmp_path):
    """隔离的临时工作目录，用于需要读写文件的测试。

    比裸 tmp_path 多一层语义：调用方可直接把它当作项目根使用。
    """
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    return workdir
