"""特征检测器集合

检测器列表:
- CryptoDetector: 加密/密码学逻辑检测
- SecurityDetector: 安全漏洞检测
- PerformanceDetector: 性能瓶颈检测
- CSSTUIDetector: CSS/TUI 界面检测
"""
from .crypto import CryptoDetector
from .css_tui import CSSTUIDetector
from .performance import PerformanceDetector
from .security import SecurityDetector

__all__ = [
    'CSSTUIDetector',
    'CryptoDetector',
    'PerformanceDetector',
    'SecurityDetector',
]
