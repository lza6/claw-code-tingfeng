"""Vector Experience Bank — 向后兼容层

已迁移至 src/core/experience_bank.py (统一经验库)
此文件保留向后兼容，自动转发到核心实现。
"""
from __future__ import annotations

from ..core.experience_bank import (
    ExperienceBank as VectorExperienceBank,
)
from ..core.experience_bank import (
    ExperienceEmbedder,
)
from ..core.experience_bank import (
    ExperienceRecord as ExperienceEntry,
)

__all__ = [
    "ExperienceEmbedder",
    "ExperienceEntry",
    "VectorExperienceBank",
]
