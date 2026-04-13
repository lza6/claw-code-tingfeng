"""
Cognition State - Cognitive provider tracking (Inspired by GoalX)

Tracks worktree-level cognitive provider state (repo-native index, gitnexus, etc.)
for the durable surface system. Each scope represents a worktree and its associated
cognitive providers with their availability and index status.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum


class InvocationKind(Enum):
    """How a cognitive provider is invoked."""
    BUILTIN = "builtin"
    BINARY = "binary"
    NPX = "npx"
    MCP = "mcp"
    NONE = "none"


class IndexState(Enum):
    """State of a provider's index."""
    MISSING = "missing"
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass
class CognitionProvider:
    """State of a single cognitive provider within a scope."""
    name: str
    invocation_kind: InvocationKind = InvocationKind.NONE
    available: bool = False
    index_state: IndexState = IndexState.UNKNOWN
    capabilities: List[str] = field(default_factory=list)
    head_revision: str = ""

    @classmethod
    def create_default(cls, name: str = "unknown") -> "CognitionProvider":
        """Create a default cognition provider."""
        return cls(name=name)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitionProvider":
        """Load from dictionary."""
        return cls(
            name=data.get("name", "unknown"),
            invocation_kind=InvocationKind(data.get("invocation_kind", "none")),
            available=data.get("available", False),
            index_state=IndexState(data.get("index_state", "unknown")),
            capabilities=data.get("capabilities", []),
            head_revision=data.get("head_revision", "")
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "invocation_kind": self.invocation_kind.value,
            "available": self.available,
            "index_state": self.index_state.value,
            "capabilities": self.capabilities,
            "head_revision": self.head_revision
        }


@dataclass
class CognitionScope:
    """A scope representing a worktree and its cognitive providers."""
    scope: str = "default"
    worktree_path: str = ""
    providers: List[CognitionProvider] = field(default_factory=list)

    @classmethod
    def create_default(cls, scope: str = "default", worktree_path: str = "") -> "CognitionScope":
        """Create a default cognition scope."""
        return cls(scope=scope, worktree_path=worktree_path)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitionScope":
        """Load from dictionary."""
        providers = [
            CognitionProvider.from_dict(p)
            for p in data.get("providers", [])
        ]
        return cls(
            scope=data.get("scope", "default"),
            worktree_path=data.get("worktree_path", ""),
            providers=providers
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "scope": self.scope,
            "worktree_path": self.worktree_path,
            "providers": [p.to_dict() for p in self.providers]
        }

    def get_provider(self, name: str) -> Optional[CognitionProvider]:
        """Get a provider by name, or None if not found."""
        for provider in self.providers:
            if provider.name == name:
                return provider
        return None

    def update_provider(self, name: str, **kwargs: Any) -> None:
        """Update fields of a provider by name. Creates if not found."""
        existing = self.get_provider(name)
        if existing is not None:
            for key, value in kwargs.items():
                if hasattr(existing, key):
                    if key == "invocation_kind" and isinstance(value, str):
                        setattr(existing, key, InvocationKind(value))
                    elif key == "index_state" and isinstance(value, str):
                        setattr(existing, key, IndexState(value))
                    else:
                        setattr(existing, key, value)
        else:
            provider = CognitionProvider(name=name)
            for key, value in kwargs.items():
                if key == "invocation_kind" and isinstance(value, str):
                    setattr(provider, key, InvocationKind(value))
                elif key == "index_state" and isinstance(value, str):
                    setattr(provider, key, IndexState(value))
                else:
                    setattr(provider, key, value)
            self.providers.append(provider)


@dataclass
class CognitionState:
    """
    Cognition state tracks worktree-level cognitive provider status,
    including repo-native index, gitnexus, and other codebase-aware
    providers that supply context to the agent.
    """
    version: int = 1
    scopes: List[CognitionScope] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def create_default(cls) -> "CognitionState":
        """Create a default cognition state with an empty default scope."""
        return cls(scopes=[CognitionScope.create_default()])

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitionState":
        """Load from dictionary."""
        scopes = [
            CognitionScope.from_dict(s)
            for s in data.get("scopes", [])
        ]
        return cls(
            version=data.get("version", 1),
            scopes=scopes if scopes else [CognitionScope.create_default()],
            updated_at=data.get("updated_at", datetime.utcnow().isoformat())
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "version": self.version,
            "scopes": [s.to_dict() for s in self.scopes],
            "updated_at": self.updated_at
        }

    def get_scope(self, scope_name: str) -> Optional[CognitionScope]:
        """Get a scope by name, or None if not found."""
        for scope in self.scopes:
            if scope.scope == scope_name:
                return scope
        return None

    def ensure_scope(self, scope_name: str, worktree_path: str = "") -> CognitionScope:
        """Get or create a scope by name."""
        existing = self.get_scope(scope_name)
        if existing is not None:
            return existing
        new_scope = CognitionScope.create_default(scope_name, worktree_path)
        self.scopes.append(new_scope)
        self.touch()
        return new_scope

    def update_provider_state(
        self,
        scope_name: str,
        provider_name: str,
        worktree_path: str = "",
        **kwargs: Any
    ) -> None:
        """Update or create a provider within a scope."""
        scope = self.ensure_scope(scope_name, worktree_path)
        scope.update_provider(provider_name, **kwargs)
        self.touch()

    def touch(self) -> None:
        """Update the timestamp."""
        self.updated_at = datetime.utcnow().isoformat()
