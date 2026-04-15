"""
CLI Config Enhancer - CLI 配置增强

从 oh-my-codex-main/src/config/ 转换而来。
增强 CLI 配置加载和原生资源管理。
"""

from dataclasses import dataclass, field
from typing import Optional
import os


@dataclass
class AgentConfig:
    """Agent配置"""
    name: str
    enabled: bool = True
    model: Optional[str] = None
    max_retries: int = 3
    timeout: int = 300


@dataclass
class NativeAsset:
    """原生资源"""
    name: str
    path: str
    type: str  # 'binary', 'script', 'config'
    executable: bool = False


@dataclass
class CLIConfig:
    """CLI配置"""
    agents: list[AgentConfig] = field(default_factory=list)
    native_assets: list[NativeAsset] = field(default_factory=list)
    debug: bool = False
    verbose: bool = False


class ConfigEnhancer:
    """配置增强器"""

    def __init__(self):
        self._config: Optional[CLIConfig] = None

    def load(self) -> CLIConfig:
        """加载配置"""
        if self._config is not None:
            return self._config

        agents = [
            AgentConfig("explore", enabled=True, model="fast"),
            AgentConfig("analyst", enabled=True, model="frontier"),
            AgentConfig("planner", enabled=True, model="frontier"),
            AgentConfig("architect", enabled=True, model="frontier"),
            AgentConfig("debugger", enabled=True, model="standard"),
            AgentConfig("executor", enabled=True, model="standard"),
            AgentConfig("code-reviewer", enabled=True, model="standard"),
            AgentConfig("security-reviewer", enabled=True, model="frontier"),
            AgentConfig("test-engineer", enabled=True, model="standard"),
        ]

        # 检测原生资源
        native_assets = self._discover_native_assets()

        self._config = CLIConfig(
            agents=agents,
            native_assets=native_assets,
            debug=os.getenv("DEBUG", "").lower() == "true",
            verbose=os.getenv("VERBOSE", "").lower() == "true",
        )
        return self._config

    def _discover_native_assets(self) -> list[NativeAsset]:
        """发现原生资源"""
        assets = []
        # 检查常见工具
        tools = ["git", "python", "node", "npm", "pip", "ruff"]
        for tool in tools:
            if self._which(toil):
                assets.append(NativeAsset(
                    name=tool,
                    path=self._which(tool),
                    type="binary",
                    executable=True,
                ))
        return assets

    def _which(self, cmd: str) -> Optional[str]:
        """查找命令路径"""
        import shutil
        return shutil.which(cmd)

    def get_agent_config(self, name: str) -> Optional[AgentConfig]:
        """获取 Agent 配置"""
        config = self.load()
        for agent in config.agents:
            if agent.name == name:
                return agent
        return None

    def is_agent_enabled(self, name: str) -> bool:
        """检查 Agent 是否启用"""
        agent = self.get_agent_config(name)
        return agent.enabled if agent else False


# 全局配置实例
_config_enhancer: Optional[ConfigEnhancer] = None


def get_config_enhancer() -> ConfigEnhancer:
    """获取配置增强器"""
    global _config_enhancer
    if _config_enhancer is None:
        _config_enhancer = ConfigEnhancer()
    return _config_enhancer