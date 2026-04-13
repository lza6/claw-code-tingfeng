"""
Surface Manager - Central coordinator for all durable surfaces

Manages lifecycle of canonical state files:
- Creation, loading, saving, validation
- Schema enforcement via JSON Schema
- Atomic writes with backup/rollback
- Change tracking and versioning
"""

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Type
from datetime import datetime
import jsonschema

from src.core.exceptions import ClawdError


class SurfaceError(ClawdError):
    """Base exception for surface operations"""
    pass


class SurfaceValidationError(SurfaceError):
    """Schema validation failed"""
    pass


class SurfaceManager:
    """
    Manages all durable surfaces for a run.

    Surfaces are stored in: .clawd/runs/{run_id}/surfaces/
    Each surface is a JSON file validated against a schema.
    """

    def __init__(self, run_dir: Path):
        """
        Initialize surface manager for a specific run.

        Args:
            run_dir: Root directory for this run (e.g., .clawd/runs/run-123)
        """
        self.run_dir = run_dir
        self.surfaces_dir = run_dir / "surfaces"
        self.schemas_dir = Path(__file__).parent / "schemas"
        self.surfaces_dir.mkdir(parents=True, exist_ok=True)

        # Cache loaded surfaces
        self._cache: Dict[str, Any] = {}

    def load_surface(
        self,
        surface_name: str,
        surface_class: Type,
        create_if_missing: bool = True
    ) -> Any:
        """
        Load a surface from disk.

        Args:
            surface_name: Name of the surface (e.g., "objective_contract")
            surface_class: Class to instantiate
            create_if_missing: Create default if file doesn't exist

        Returns:
            Instance of surface_class
        """
        # Check cache first
        if surface_name in self._cache:
            return self._cache[surface_name]

        surface_path = self.surfaces_dir / f"{surface_name}.json"

        if not surface_path.exists():
            if create_if_missing:
                # Create default instance
                instance = surface_class.create_default()
                self.save_surface(surface_name, instance)
                self._cache[surface_name] = instance
                return instance
            else:
                raise SurfaceError(f"Surface not found: {surface_name}")

        # Load from disk
        with open(surface_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Validate against schema
        self._validate_schema(surface_name, data)

        # Instantiate
        instance = surface_class.from_dict(data)
        self._cache[surface_name] = instance
        return instance

    def save_surface(self, surface_name: str, surface: Any) -> None:
        """
        Save a surface to disk atomically.

        Args:
            surface_name: Name of the surface
            surface: Surface instance with to_dict() method
        """
        surface_path = self.surfaces_dir / f"{surface_name}.json"
        backup_path = surface_path.with_suffix('.json.bak')

        # Convert to dict
        data = surface.to_dict()

        # Validate against schema
        self._validate_schema(surface_name, data)

        # Atomic write: write to temp, then rename
        temp_path = surface_path.with_suffix('.json.tmp')

        try:
            # Backup existing file
            if surface_path.exists():
                shutil.copy2(surface_path, backup_path)

            # Write to temp
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_path.replace(surface_path)

            # Update cache
            self._cache[surface_name] = surface

        except Exception as e:
            # Rollback on error
            if backup_path.exists() and not surface_path.exists():
                backup_path.rename(surface_path)
            raise SurfaceError(f"Failed to save surface {surface_name}: {e}")
        finally:
            # Cleanup temp file
            if temp_path.exists():
                temp_path.unlink()

    def _validate_schema(self, surface_name: str, data: Dict[str, Any]) -> None:
        """
        Validate surface data against JSON schema.

        Args:
            surface_name: Name of the surface
            data: Data to validate

        Raises:
            SurfaceValidationError: If validation fails
        """
        schema_path = self.schemas_dir / f"{surface_name}.schema.json"

        if not schema_path.exists():
            # No schema defined, skip validation
            return

        with open(schema_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)

        try:
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.ValidationError as e:
            raise SurfaceValidationError(
                f"Schema validation failed for {surface_name}: {e.message}"
            )

    def list_surfaces(self) -> list[str]:
        """List all available surfaces in this run."""
        return [
            p.stem for p in self.surfaces_dir.glob("*.json")
            if not p.name.endswith('.bak') and not p.name.endswith('.tmp')
        ]

    def snapshot(self, tag: str) -> Path:
        """
        Create a snapshot of all surfaces.

        Args:
            tag: Snapshot identifier

        Returns:
            Path to snapshot directory
        """
        snapshot_dir = self.run_dir / "snapshots" / f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Copy all surfaces
        for surface_file in self.surfaces_dir.glob("*.json"):
            if not surface_file.name.endswith('.bak') and not surface_file.name.endswith('.tmp'):
                shutil.copy2(surface_file, snapshot_dir / surface_file.name)

        return snapshot_dir

    def restore_snapshot(self, snapshot_dir: Path) -> None:
        """
        Restore surfaces from a snapshot.

        Args:
            snapshot_dir: Path to snapshot directory
        """
        if not snapshot_dir.exists():
            raise SurfaceError(f"Snapshot not found: {snapshot_dir}")

        # Clear cache
        self._cache.clear()

        # Restore all surfaces
        for surface_file in snapshot_dir.glob("*.json"):
            shutil.copy2(surface_file, self.surfaces_dir / surface_file.name)

    def clear_cache(self) -> None:
        """Clear the in-memory cache."""
        self._cache.clear()
