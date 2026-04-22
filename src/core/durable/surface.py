"""
Surface Base Class - Atomic state management with versioning.
Inspired by GoalX (Project B).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

from ...utils.file_ops import atomic_write_json

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="Surface")

@dataclass
class Surface:
    """
    Base class for all durable surfaces.

    Provides versioning and basic serialization.
    """
    version: int = 1
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        """Create a surface from a dictionary."""
        # This is a basic implementation; subclasses should override for complex nested structures
        fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**fields)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary."""
        return asdict(self)

class SurfaceManager(Generic[T]):
    """
    Manager for a specific surface type.

    Handles atomic reading and writing with optimistic concurrency control.
    """
    def __init__(self, surface_cls: type[T], storage_path: Path):
        self.surface_cls = surface_cls
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> T:
        """Load the surface from storage."""
        if not self.storage_path.exists():
            return self.surface_cls()

        try:
            import json
            data = json.loads(self.storage_path.read_text(encoding='utf-8'))
            return self.surface_cls.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load surface {self.surface_cls.__name__} from {self.storage_path}: {e}")
            return self.surface_cls()

    def save(self, surface: T) -> None:
        """Save the surface atomically."""
        surface.updated_at = datetime.utcnow().isoformat()
        atomic_write_json(self.storage_path, surface.to_dict())

    def update(self, updater: Callable[[T], None]) -> T:
        """
        Update the surface atomically with optimistic concurrency control.

        Args:
            updater: A function that modifies the surface instance in-place.

        Returns:
            The updated surface.
        """
        # Simple implementation for now: load, update, increment version, save
        # In a real concurrent environment, we'd need a file lock here
        surface = self.load()
        updater(surface)
        surface.version += 1
        self.save(surface)
        return surface

    def update_with_retry(self, updater: Callable[[T], None], max_retries: int = 3) -> T:
        """Update with retries in case of concurrent modification."""
        for attempt in range(max_retries):
            try:
                # We check the version before saving
                surface = self.load()
                current_version = surface.version

                updater(surface)

                # Check if file changed since we loaded it
                reloaded = self.load()
                if reloaded.version != current_version:
                    if attempt == max_retries - 1:
                        raise RuntimeError(f"Concurrent modification of {self.surface_cls.__name__} after {max_retries} attempts")
                    time.sleep(0.1 * (attempt + 1))
                    continue

                surface.version += 1
                self.save(surface)
                return surface
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                time.sleep(0.1 * (attempt + 1))

        return self.load() # Fallback
