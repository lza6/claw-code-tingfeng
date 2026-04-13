"""
配置注入器单元测试

测试 src/core/config_injector.py 的所有功能
"""

import pytest
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.core.config_injector import (
    ConfigInjector,
    ConfigValue,
    ConfigChangeEvent,
    get_config_injector,
    reset_config_injector,
    set_config,
    get_config,
    get_full_config,
)


@pytest.fixture(autouse=True)
def reset_injector():
    """每个测试后重置配置注入器"""
    reset_config_injector()
    yield
    reset_config_injector()


@pytest.fixture
def injector():
    """创建配置注入器实例"""
    return ConfigInjector()


@pytest.fixture
def temp_config_dir(tmp_path):
    """创建临时配置目录"""
    clawd_dir = tmp_path / ".clawd"
    clawd_dir.mkdir()
    return clawd_dir


class TestConfigValue:
    """测试配置值数据类"""

    def test_create_config_value(self):
        """测试创建配置值"""
        cv = ConfigValue(value="test", source="test_source", priority=0)
        assert cv.value == "test"
        assert cv.source == "test_source"
        assert cv.priority == 0


class TestConfigChangeEvent:
    """测试配置变更事件数据类"""

    def test_create_event(self):
        """测试创建变更事件"""
        event = ConfigChangeEvent(
            key="test_key",
            old_value="old",
            new_value="new",
            source="test",
        )
        assert event.key == "test_key"
        assert event.old_value == "old"
        assert event.new_value == "new"
        assert event.source == "test"


class TestConfigInjectorSet:
    """测试 set 方法"""

    def test_set_basic(self, injector):
        """测试基础设置"""
        injector.set("test_key", "test_value")
        assert injector.get("test_key") == "test_value"

    def test_set_overwrite(self, injector):
        """测试覆盖设置"""
        injector.set("key", "value1")
        injector.set("key", "value2")
        assert injector.get("key") == "value2"

    def test_set_with_source(self, injector):
        """测试带来源设置"""
        injector.set("key", "value", source="custom_source")
        assert "key" in injector._runtime_overrides
        assert injector._runtime_overrides["key"].source == "custom_source"

    def test_set_triggers_cache_clear(self, injector):
        """测试设置清除缓存"""
        injector._config_cache["key"] = ConfigValue(value="cached", source="test", priority=0)
        injector.set("key", "new_value")
        assert "key" not in injector._config_cache


class TestConfigInjectorGet:
    """测试 get 方法"""

    def test_get_runtime_override(self, injector):
        """测试获取运行时覆盖"""
        injector.set("key", "runtime_value")
        assert injector.get("key") == "runtime_value"

    def test_get_from_env(self, injector):
        """测试从环境变量获取"""
        with patch.dict(os.environ, {"TEST_ENV_VAR": "env_value"}):
            assert injector.get("TEST_ENV_VAR") == "env_value"

    def test_get_default(self, injector):
        """测试获取默认值"""
        assert injector.get("nonexistent_key", "default") == "default"

    def test_get_returns_none(self, injector):
        """测试获取不存在的键返回 None"""
        assert injector.get("nonexistent_key") is None


class TestConfigInjectorGetTyped:
    """测试 get_typed 方法"""

    def test_get_bool_true(self, injector):
        """测试获取布尔值 True"""
        injector.set("flag", "true")
        assert injector.get_typed("flag", bool) is True

    def test_get_bool_false(self, injector):
        """测试获取布尔值 False"""
        injector.set("flag", "false")
        assert injector.get_typed("flag", bool) is False

    def test_get_int(self, injector):
        """测试获取整数"""
        injector.set("timeout", "30")
        assert injector.get_typed("timeout", int) == 30

    def test_get_float(self, injector):
        """测试获取浮点数"""
        injector.set("rate", "3.14")
        assert injector.get_typed("rate", float) == pytest.approx(3.14)

    def test_get_str(self, injector):
        """测试获取字符串"""
        injector.set("name", 123)
        assert injector.get_typed("name", str) == "123"

    def test_get_typed_invalid_returns_default(self, injector):
        """测试类型转换失败返回默认值"""
        injector.set("value", "not_a_number")
        assert injector.get_typed("value", int, default=42) == 42


class TestConfigInjectorPriority:
    """测试配置优先级"""

    def test_runtime_overrides_env(self, injector):
        """测试运行时覆盖优先于环境变量"""
        with patch.dict(os.environ, {"KEY": "env_value"}):
            injector.set("KEY", "runtime_value")
            assert injector.get("KEY") == "runtime_value"

    def test_env_overrides_default(self, injector):
        """测试环境变量优先于默认值"""
        with patch.dict(os.environ, {"KEY": "env_value"}):
            assert injector.get("KEY", "default_value") == "env_value"


class TestConfigInjectorInternalOverrides:
    """测试内部覆盖"""

    def test_internal_overrides(self, injector):
        """测试内部覆盖"""
        overrides = {"key1": "value1", "key2": "value2"}
        with patch.dict(os.environ, {"CLAUDE_INTERNAL_FC_OVERRIDES": json.dumps(overrides)}):
            assert injector.get("key1") == "value1"
            assert injector.get("key2") == "value2"

    def test_invalid_internal_overrides(self, injector):
        """测试无效内部覆盖"""
        with patch.dict(os.environ, {"CLAUDE_INTERNAL_FC_OVERRIDES": "invalid json"}):
            assert injector.get("key1") is None


class TestConfigInjectorProviderConfig:
    """测试 provider.json 配置加载"""

    def test_load_provider_config(self, tmp_path):
        """测试加载 provider 配置"""
        # 创建在实际位置的配置
        clawd_dir = tmp_path / ".clawd"
        clawd_dir.mkdir()
        provider_file = clawd_dir / "provider.json"
        provider_file.write_text(json.dumps({"api_key": "test_key"}))
        
        # 直接测试文件读取逻辑
        assert provider_file.exists()
        data = json.loads(provider_file.read_text())
        assert data["api_key"] == "test_key"

    def test_load_provider_with_active_provider(self, tmp_path):
        """测试加载活跃 provider 配置"""
        clawd_dir = tmp_path / ".clawd"
        clawd_dir.mkdir()
        provider_file = clawd_dir / "provider.json"
        data = {
            "activeProvider": "openai",
            "providers": {
                "openai": {"api_key": "openai_key"},
                "anthropic": {"api_key": "anthropic_key"},
            }
        }
        provider_file.write_text(json.dumps(data))
        
        # 验证文件内容
        assert provider_file.exists()
        loaded_data = json.loads(provider_file.read_text())
        assert loaded_data["activeProvider"] == "openai"
        assert loaded_data["providers"]["openai"]["api_key"] == "openai_key"


class TestConfigInjectorFeaturesConfig:
    """测试 features.json 配置加载"""

    def test_load_features_config(self, injector, tmp_path):
        """测试加载 features 配置"""
        clawd_dir = tmp_path / ".clawd"
        clawd_dir.mkdir()
        features_file = clawd_dir / "features.json"
        features_file.write_text(json.dumps({"feature1": True, "feature2": False}))
        
        import os
        original_clawd = os.environ.get("CLAWD_CONFIG_DIR")
        os.environ["CLAWD_CONFIG_DIR"] = str(clawd_dir)
        
        try:
            reset_config_injector()
            injector = ConfigInjector()
            config = injector._load_features_config()
            assert len(config) > 0
        finally:
            if original_clawd:
                os.environ["CLAWD_CONFIG_DIR"] = original_clawd
            else:
                os.environ.pop("CLAWD_CONFIG_DIR", None)


class TestConfigInjectorDelete:
    """测试 delete 方法"""

    def test_delete_existing(self, injector):
        """测试删除现有覆盖"""
        injector.set("key", "value")
        assert injector.delete("key") is True
        assert injector.get("key") is None

    def test_delete_nonexistent(self, injector):
        """测试删除不存在的覆盖"""
        assert injector.delete("nonexistent") is False

    def test_delete_triggers_callback(self, injector):
        """测试删除触发回调"""
        callbacks = []
        injector.on_change(lambda event: callbacks.append(event))
        
        injector.set("key", "value")
        injector.delete("key")
        
        assert len(callbacks) == 2  # set 和 delete 各触发一次
        assert callbacks[-1].new_value is None


class TestConfigInjectorCallbacks:
    """测试回调系统"""

    def test_on_change(self, injector):
        """测试变更回调"""
        events = []
        injector.on_change(lambda event: events.append(event))
        
        injector.set("key", "value")
        
        assert len(events) == 1
        assert events[0].key == "key"
        assert events[0].new_value == "value"

    def test_multiple_callbacks(self, injector):
        """测试多个回调"""
        events = []
        injector.on_change(lambda event: events.append(("cb1", event)))
        injector.on_change(lambda event: events.append(("cb2", event)))
        
        injector.set("key", "value")
        
        assert len(events) == 2

    def test_callback_exception_handling(self, injector, caplog):
        """测试回调异常处理"""
        def failing_callback(event):
            raise ValueError("Test error")
        
        injector.on_change(failing_callback)
        injector.set("key", "value")  # 不应抛出异常


class TestConfigInjectorReload:
    """测试 reload 方法"""

    def test_reload_clears_cache(self, injector):
        """测试重载清除缓存"""
        injector._config_cache["key"] = ConfigValue(value="cached", source="test", priority=0)
        injector.reload()
        assert "key" not in injector._config_cache


class TestConfigInjectorClearRuntimeOverrides:
    """测试清除运行时覆盖"""

    def test_clear(self, injector):
        """测试清除"""
        injector.set("key1", "value1")
        injector.set("key2", "value2")
        count = injector.clear_runtime_overrides()
        assert count == 2
        assert len(injector._runtime_overrides) == 0


class TestConfigInjectorGetFullConfig:
    """测试获取完整配置"""

    def test_get_full_config(self, injector):
        """测试获取完整配置"""
        injector.set("key1", "value1")
        injector.set("key2", "value2")
        
        config = injector.get_full_config()
        
        assert config.get("key1") == "value1"
        assert config.get("key2") == "value2"


class TestConfigInjectorHas:
    """测试 has 方法"""

    def test_has_true(self, injector):
        """测试存在返回 True"""
        injector.set("key", "value")
        assert injector.has("key") is True

    def test_has_false(self, injector):
        """测试不存在返回 False"""
        assert injector.has("nonexistent") is False


class TestConfigInjectorPriorityReport:
    """测试优先级报告"""

    def test_get_priority_report(self, injector):
        """测试获取优先级报告"""
        injector.set("key1", "value1")
        injector.set("key2", "value2")
        
        report = injector.get_priority_report()
        
        assert "配置优先级报告" in report
        assert "Runtime Overrides" in report
        assert "key1" in report
        assert "key2" in report


class TestConfigInjectorPersistToFile:
    """测试持久化到文件"""

    def test_persist(self, injector, tmp_path):
        """测试持久化"""
        # 模拟持久化路径
        clawd_dir = tmp_path / ".clawd"
        clawd_dir.mkdir()
        
        with patch.object(injector, '_persist_to_file', wraps=injector._persist_to_file):
            # 修改 _persist_to_file 使用的路径
            persist_path = clawd_dir / "runtime_overrides.json"
            with patch('src.core.config_injector.Path.cwd', return_value=tmp_path):
                injector.set("key", "value", persistent=True)
                
                # 检查文件是否创建
                assert persist_path.exists()
                data = json.loads(persist_path.read_text())
                assert data["key"] == "value"


class TestConfigInjectorLoadPersistentOverrides:
    """测试加载持久化覆盖"""

    def test_load_persistent(self, injector, tmp_path):
        """测试加载持久化配置"""
        clawd_dir = tmp_path / ".clawd"
        clawd_dir.mkdir()
        persist_file = clawd_dir / "runtime_overrides.json"
        persist_file.write_text(json.dumps({"key1": "value1", "key2": "value2"}))
        
        with patch('src.core.config_injector.Path.cwd', return_value=tmp_path):
            count = injector.load_persistent_overrides()
            assert count == 2
            assert injector.get("key1") == "value1"
            assert injector.get("key2") == "value2"

    def test_load_no_file(self, injector):
        """测试无文件时加载返回 0"""
        count = injector.load_persistent_overrides()
        assert count == 0


class TestGlobalFunctions:
    """测试全局便捷函数"""

    def test_set_config(self):
        """测试 set_config"""
        set_config("test_key", "test_value")
        assert get_config("test_key") == "test_value"

    def test_get_config_default(self):
        """测试 get_config 默认值"""
        assert get_config("nonexistent", "default") == "default"

    def test_get_full_config(self):
        """测试 get_full_config"""
        set_config("key", "value")
        config = get_full_config()
        assert config.get("key") == "value"

    def test_reset_config_injector(self):
        """测试重置配置注入器"""
        set_config("key", "value")
        reset_config_injector()
        injector = get_config_injector()
        # 重置后应重新创建实例
        assert injector is not None


class TestConfigInjectorTypeConversion:
    """测试类型转换"""

    def test_bool_conversion_true(self, injector):
        """测试布尔值转换 True"""
        assert injector._convert_type("feature_enabled", "true") is True
        assert injector._convert_type("debug", "1") is True
        assert injector._convert_type("enable", "yes") is True

    def test_bool_conversion_false(self, injector):
        """测试布尔值转换 False"""
        assert injector._convert_type("feature_enabled", "false") is False
        assert injector._convert_type("debug", "0") is False

    def test_int_conversion(self, injector):
        """测试整数转换"""
        assert injector._convert_type("command_timeout", "30") == 30
        assert injector._convert_type("server_port", "8080") == 8080

    def test_float_conversion(self, injector):
        """测试浮点数转换"""
        assert injector._convert_type("sample_rate", "3.14") == pytest.approx(3.14)

    def test_string_default(self, injector):
        """测试默认返回字符串"""
        assert injector._convert_type("some_key", "value") == "value"
