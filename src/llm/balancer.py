from __future__ import annotations

import json
import logging
import random
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class ProviderInstance:
    id: str
    name: str
    provider: str
    base_url: str
    api_key: str
    weight: int = 1
    enabled: bool = True
    failure_count: int = 0
    last_failure_time: float = 0

class LLMLoadBalancer:
    """LLM 负载均衡器 - 实现多 Key 轮询与故障转移"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LLMLoadBalancer, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.providers: list[ProviderInstance] = []
        self.strategy = "round-robin"
        self.current_index = 0
        self.config_path = Path.home() / ".clawd" / "providers.json"
        self.load_config()
        self._initialized = True

    def load_config(self):
        """从磁盘加载配置"""
        if not self.config_path.exists():
            return

        try:
            data = json.loads(self.config_path.read_text(encoding='utf-8'))
            self.strategy = data.get("strategy", "round-robin")
            new_providers = []
            for p in data.get("providers", []):
                new_providers.append(ProviderInstance(
                    id=p["id"],
                    name=p["name"],
                    provider=p["provider"],
                    base_url=p["base_url"],
                    api_key=p["api_key"],
                    weight=p.get("weight", 1),
                    enabled=p.get("enabled", True)
                ))
            self.providers = new_providers
            logger.info(f"已加载 {len(self.providers)} 个 LLM Provider 配置")
        except Exception as e:
            logger.error(f"加载 Provider 配置文件失败: {e}")

    def get_next_config(self) -> ProviderInstance | None:
        """根据策略选择下一个可用的 Provider"""
        available = [p for p in self.providers if p.enabled and p.failure_count < 5]
        if not available:
            return None

        if self.strategy == "random":
            return random.choice(available)

        if self.strategy == "round-robin":
            instance = available[self.current_index % len(available)]
            self.current_index += 1
            return instance

        # 默认返回第一个
        return available[0]

    def report_failure(self, provider_id: str):
        """记录失败，用于熔断逻辑"""
        for p in self.providers:
            if p.id == provider_id:
                p.failure_count += 1
                import time
                p.last_failure_time = time.time()
                logger.warning(f"Provider {p.name} 失败次数增加至 {p.failure_count}")

    def report_success(self, provider_id: str):
        """记录成功，重置失败计数"""
        for p in self.providers:
            if p.id == provider_id:
                p.failure_count = 0

def get_balancer() -> LLMLoadBalancer:
    return LLMLoadBalancer()
