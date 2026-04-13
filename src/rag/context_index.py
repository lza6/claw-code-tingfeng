from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
import os
import ast

@dataclass
class ContextNode:
    file_path: str
    symbols: List[str] = field(default_factory=list)
    upstream: List[str] = field(default_factory=list)
    downstream: List[str] = field(default_factory=list)
    last_indexed: str = ""

class ContextIndex:
    """结构化代码全景索引 (借鉴 goalx-main/cli/context_index.go)
    
    职责:
    - 统一管理文件、符号、依赖的全景关系
    - 为 Agent 提供精准的“修改影响范围” (Impact Scope)
    """
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.nodes: Dict[str, ContextNode] = {}
        self.symbol_to_file: Dict[str, str] = {}
        
    def index_file(self, rel_path: str):
        full_path = os.path.join(self.root_dir, rel_path)
        if not os.path.exists(full_path) or not rel_path.endswith('.py'):
            return

        try:
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                tree = ast.parse(f.read())
                
            symbols = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    symbols.append(node.name)
                    self.symbol_to_file[node.name] = rel_path
            
            if rel_path not in self.nodes:
                self.nodes[rel_path] = ContextNode(file_path=rel_path)
            
            self.nodes[rel_path].symbols = symbols
            self.nodes[rel_path].last_indexed = "indexed" # 占位符
        except Exception:
            pass

    def get_impact_scope(self, file_path: str) -> Set[str]:
        """获取修改某个文件的影响范围"""
        scope = {file_path}
        if file_path in self.nodes:
            # 加入直接下游依赖 (简化实现)
            scope.update(self.nodes[file_path].downstream)
        return scope
