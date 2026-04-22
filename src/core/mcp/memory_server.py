"""MCP 服务器: Memory Server (长期记忆)

参考: oh-my-codex-main/src/mcp/memory_server.ts
提供长期记忆存储和检索能力。

设计:
    - 支持实体 (Entity) 和观察 (Observation) 存储
    - 支持关系图谱 (Knowledge Graph)
    - 语义搜索 (通过 TextIndexer)
    - LTM 持久化到 .clawd/memory/
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.memory.enterprise_ltm import EnterpriseLongTermMemory
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MemoryEntity:
    """记忆实体"""
    id: str
    type: str
    name: str
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


@dataclass
class MemoryObservation:
    """记忆观察"""
    id: str
    entity_id: str
    content: str
    source: str = ""  # 来源 (session/tool/agent)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass
class MemoryRelation:
    """实体关系"""
    from_id: str
    to_id: str
    relation_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryServer:
    """MCP Memory Server - 长期记忆管理"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.memory_dir = project_root / ".clawd" / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # 子目录
        (self.memory_dir / "entities").mkdir(exist_ok=True)
        (self.memory_dir / "observations").mkdir(exist_ok=True)
        (self.memory_dir / "relations").mkdir(exist_ok=True)
        (self.memory_dir / "index").mkdir(exist_ok=True)

        # 集成 EnterpriseLTM
        self.ltm = EnterpriseLongTermMemory(
            db_path=self.memory_dir / "ltm.db"
        )

    # ==================== Entity 操作 ====================

    def create_entity(self, entity: MemoryEntity) -> str:
        """创建实体"""
        path = self.memory_dir / "entities" / f"{entity.id}.json"
        path.write_text(json.dumps(entity.__dict__, indent=2, ensure_ascii=False))
        self.ltm.store_entity(entity.id, entity.__dict__)
        logger.info(f"Created entity: {entity.id}")
        return entity.id

    def get_entity(self, entity_id: str) -> MemoryEntity | None:
        """获取实体"""
        path = self.memory_dir / "entities" / f"{entity_id}.json"
        if path.exists():
            data = json.loads(path.read_text())
            return MemoryEntity(**data)
        return None

    def update_entity(self, entity_id: str, updates: dict) -> MemoryEntity | None:
        """更新实体"""
        entity = self.get_entity(entity_id)
        if not entity:
            return None
        for k, v in updates.items():
            if hasattr(entity, k):
                setattr(entity, k, v)
        entity.updated_at = datetime.now().isoformat()
        path = self.memory_dir / "entities" / f"{entity_id}.json"
        path.write_text(json.dumps(entity.__dict__, indent=2, ensure_ascii=False))
        return entity

    def list_entities(self, entity_type: str | None = None) -> list[MemoryEntity]:
        """列出实体"""
        entities = []
        for p in (self.memory_dir / "entities").glob("*.json"):
            data = json.loads(p.read_text())
            if entity_type is None or data.get("type") == entity_type:
                entities.append(MemoryEntity(**data))
        return entities

    def delete_entity(self, entity_id: str) -> bool:
        """删除实体"""
        path = self.memory_dir / "entities" / f"{entity_id}.json"
        if path.exists():
            path.unlink()
            # 删除相关观察和关系
            for obs_path in (self.memory_dir / "observations").glob(f"{entity_id}_*.json"):
                obs_path.unlink()
            for rel_path in (self.memory_dir / "relations").glob(f"*_{entity_id}_*.json"):
                rel_path.unlink()
            return True
        return False

    # ==================== Observation 操作 ====================

    def add_observation(
        self,
        entity_id: str,
        content: str,
        source: str = "",
        metadata: dict | None = None,
    ) -> str:
        """添加观察记录"""
        import uuid

        obs_id = f"obs_{uuid.uuid4().hex[:12]}"
        obs = MemoryObservation(
            id=obs_id,
            entity_id=entity_id,
            content=content,
            source=source,
            metadata=metadata or {},
            created_at=datetime.now().isoformat(),
        )
        path = self.memory_dir / "observations" / f"{obs_id}.json"
        path.write_text(json.dumps(obs.__dict__, indent=2, ensure_ascii=False))

        # 索引到 LTM
        self.ltm.store_observation(entity_id, content, metadata)

        logger.info(f"Added observation {obs_id} to entity {entity_id}")
        return obs_id

    def get_observations(self, entity_id: str) -> list[MemoryObservation]:
        """获取实体的所有观察"""
        observations = []
        for p in (self.memory_dir / "observations").glob(f"{entity_id}_*.json"):
            data = json.loads(p.read_text())
            observations.append(MemoryObservation(**data))
        return observations

    # ==================== Relation 操作 ====================

    def add_relation(
        self,
        from_id: str,
        to_id: str,
        relation_type: str,
        metadata: dict | None = None,
    ) -> bool:
        """添加实体关系"""
        import uuid

        rel_id = f"rel_{uuid.uuid4().hex[:12]}"
        rel = {
            "id": rel_id,
            "from_id": from_id,
            "to_id": to_id,
            "relation_type": relation_type,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat(),
        }
        path = (
            self.memory_dir
            / "relations"
            / f"{from_id}_{relation_type}_{to_id}.json"
        )
        path.write_text(json.dumps(rel, indent=2, ensure_ascii=False))
        self.ltm.store_relation(from_id, to_id, relation_type)
        return True

    def get_related_entities(self, entity_id: str) -> list[tuple[str, str]]:
        """获取关联实体"""
        relations = []
        for p in (self.memory_dir / "relations").glob(f"*_{entity_id}_*.json"):
            data = json.loads(p.read_text())
            relations.append((data["to_id"], data["relation_type"]))
        for p in (self.memory_dir / "relations").glob(f"{entity_id}_*_*.json"):
            data = json.loads(p.read_text())
            relations.append((data["from_id"], data["relation_type"]))
        return relations

    # ==================== 语义搜索 ====================

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """语义搜索记忆"""
        # 使用 LTM 的嵌入搜索
        return self.ltm.search(query, limit=limit)

    # ==================== 统计 ====================

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        entity_count = len(list((self.memory_dir / "entities").glob("*.json")))
        obs_count = len(list((self.memory_dir / "observations").glob("*.json")))
        rel_count = len(list((self.memory_dir / "relations").glob("*.json")))
        return {
            "entities": entity_count,
            "observations": obs_count,
            "relations": rel_count,
        }


def create_memory_server(project_root: Path | None = None) -> MemoryServer:
    """工厂函数: 创建 Memory Server"""
    if project_root is None:
        project_root = Path.cwd()
    return MemoryServer(project_root)


# MCP 工具定义
MEMORY_SERVER_TOOLS = {
    "create_entity": {
        "name": "create_entity",
        "description": "Create a new memory entity",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "type": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "metadata": {"type": "object", "default": {}},
            },
            "required": ["id", "type", "name", "description"],
        },
    },
    "get_entity": {
        "name": "get_entity",
        "description": "Get entity by ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
            },
            "required": ["entity_id"],
        },
    },
    "add_observation": {
        "name": "add_observation",
        "description": "Add observation to an entity",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "content": {"type": "string"},
                "source": {"type": "string", "default": ""},
                "metadata": {"type": "object", "default": {}},
            },
            "required": ["entity_id", "content"],
        },
    },
    "search_memory": {
        "name": "search_memory",
        "description": "Semantic search memory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    "get_stats": {
        "name": "get_stats",
        "description": "Get memory statistics",
        "inputSchema": {"type": "object", "properties": {}},
    },
}

__all__ = [
    "MEMORY_SERVER_TOOLS",
    "MemoryEntity",
    "MemoryObservation",
    "MemoryRelation",
    "MemoryServer",
    "create_memory_server",
]
