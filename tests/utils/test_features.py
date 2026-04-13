"""Tests for FeatureFlagManager"""
import pytest
from pathlib import Path
from src.utils.features import FeatureFlagManager, DEFAULT_FEATURES


@pytest.fixture
def feature_manager(tmp_path):
    """Create a fresh FeatureFlagManager for each test"""
    manager = FeatureFlagManager(workdir=tmp_path)
    manager._initialized = False  # Reset initialization flag
    return manager


class TestFeatureFlagManager:
    
    def test_initialization(self, feature_manager, tmp_path):
        """Test feature manager initialization"""
        feature_manager.initialize()
        assert feature_manager._initialized is True
        assert (tmp_path / ".clawd" / "features.json").exists()
    
    def test_is_enabled_default(self, feature_manager):
        """Test default feature values"""
        feature_manager.initialize()
        
        # Test some default values
        assert feature_manager.is_enabled("ultraplan") is True
        assert feature_manager.is_enabled("god_mode") is False
    
    def test_set_feature_runtime(self, feature_manager):
        """Test runtime feature override (non-persistent)"""
        feature_manager.initialize()
        
        # Set runtime override
        feature_manager.set_feature("debug_tracing", True, persistent=False)
        assert feature_manager.is_enabled("debug_tracing") is True
        
        # Should be in runtime overrides
        assert "debug_tracing" in feature_manager._runtime_overrides
    
    def test_set_feature_persistent(self, feature_manager, tmp_path):
        """Test persistent feature override"""
        feature_manager.initialize()
        
        # Set persistent override
        feature_manager.set_feature("agent_teams", False, persistent=True)
        
        # Check file was updated
        features_file = tmp_path / ".clawd" / "features.json"
        assert features_file.exists()
        
        import json
        with open(features_file) as f:
            saved_features = json.load(f)
        assert saved_features["agent_teams"] is False
    
    def test_clear_runtime_override(self, feature_manager):
        """Test clearing runtime override"""
        feature_manager.initialize()
        
        # Set and clear runtime override
        feature_manager.set_feature("debug_tracing", True, persistent=False)
        assert feature_manager.is_enabled("debug_tracing") is True
        
        feature_manager.clear_runtime_override("debug_tracing")
        # Should revert to default
        assert feature_manager.is_enabled("debug_tracing") is False
    
    def test_environment_variable_override(self, feature_manager, monkeypatch):
        """Test environment variable takes precedence"""
        monkeypatch.setenv("CLAWD_FEATURE_GOD_MODE", "true")
        feature_manager.initialize()
        
        assert feature_manager.is_enabled("god_mode") is True
    
    def test_internal_fc_overrides(self, feature_manager, monkeypatch):
        """Test CLAUDE_INTERNAL_FC_OVERRIDES"""
        import json
        overrides = {"god_mode": True, "debug_tracing": True}
        monkeypatch.setenv("CLAUDE_INTERNAL_FC_OVERRIDES", json.dumps(overrides))
        
        feature_manager.initialize()
        
        assert feature_manager.is_enabled("god_mode") is True
        assert feature_manager.is_enabled("debug_tracing") is True
    
    def test_get_override_report(self, feature_manager):
        """Test override report generation"""
        feature_manager.initialize()
        
        # Set some overrides
        feature_manager.set_feature("debug_tracing", True, persistent=False)
        
        report = feature_manager.get_override_report()
        assert "debug_tracing" in report
        # Source is tracked as runtime_override (not runtime_set_feature)
        assert report["debug_tracing"] in ["runtime_override", "runtime_set_feature"]
    
    def test_get_features_by_category(self, feature_manager):
        """Test querying features by category"""
        feature_manager.initialize()
        
        perf_features = feature_manager.get_features_by_category("performance")
        assert len(perf_features) > 0
        assert "enable_output_compression" in perf_features
    
    def test_change_callback(self, feature_manager):
        """Test feature change callback"""
        feature_manager.initialize()
        
        changes = []
        def on_change(name, value):
            changes.append((name, value))
        
        feature_manager.register_change_callback(on_change)
        feature_manager.set_feature("debug_tracing", True)
        
        assert len(changes) == 1
        assert changes[0] == ("debug_tracing", True)
    
    def test_reset_to_defaults(self, feature_manager):
        """Test resetting to default values"""
        feature_manager.initialize()
        
        # Change some features
        feature_manager.set_feature("god_mode", True)
        feature_manager.set_feature("debug_tracing", True)
        
        # Reset
        feature_manager.reset_to_defaults()
        
        assert feature_manager.is_enabled("god_mode") is False
        assert feature_manager.is_enabled("debug_tracing") is False
    
    def test_priority_order(self, feature_manager, monkeypatch):
        """Test configuration priority order"""
        import json
        
        # Set via env var
        monkeypatch.setenv("CLAWD_FEATURE_GOD_MODE", "false")
        
        # Set via internal overrides (should take precedence)
        overrides = {"god_mode": True}
        monkeypatch.setenv("CLAUDE_INTERNAL_FC_OVERRIDES", json.dumps(overrides))
        
        feature_manager.initialize()
        
        # Internal overrides should win
        assert feature_manager.is_enabled("god_mode") is True
        
        # Runtime override should win over everything
        feature_manager.set_feature("god_mode", False, persistent=False)
        assert feature_manager.is_enabled("god_mode") is False


class TestFeatureMetadata:
    
    def test_metadata_registration(self, feature_manager):
        """Test that metadata is registered for default features"""
        feature_manager.initialize()
        
        metadata = feature_manager.get_metadata("god_mode")
        assert metadata is not None
        assert metadata.name == "god_mode"
        assert metadata.category == "security"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
