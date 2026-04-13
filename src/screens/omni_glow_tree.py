"""Omni-Glow ThinkingTree 组件

实时思维树:
- Unicode 盲文字符动态渲染 Decision-Chain
- 每个节点显示推理置信度
- 实时状态更新
"""
import time

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from .omni_glow_models import ThinkingNode
from .omni_glow_rendering import render_block_progress, render_braille_connection


class ThinkingTree(VerticalScroll):
    """实时思维树 — 使用盲文/2x2 Block 字符渲染

    特性:
    - Unicode 盲文字符动态渲染 Decision-Chain
    - 每个节点显示推理置信度
    - 实时状态更新
    """

    DEFAULT_CSS = """
    ThinkingTree {
        width: 1fr;
        padding: 0 1;
    }
    ThinkingTree .tree-title {
        text-style: bold;
        color: $primary;
        padding: 0 1;
    }
    ThinkingTree .tree-node {
        font-family: monospace;
        padding: 0 1;
        margin: 0;
    }
    ThinkingTree .node-pending {
        color: $text-muted;
    }
    ThinkingTree .node-running {
        color: #9D4BDB;
    }
    ThinkingTree .node-success {
        color: #4FAF6F;
    }
    ThinkingTree .node-error {
        color: #D94F4F;
    }
    ThinkingTree .confidence-badge {
        padding: 0 1;
        margin-left: 1;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._nodes: dict[int, ThinkingNode] = {}
        self._next_id: int = 0
        self._last_refresh: float = 0
        self._refresh_interval: float = 0.15  # 150ms 刷新上限，防止 UI 抖动

    def compose(self) -> ComposeResult:
        yield Label("🧠 Thinking Tree", classes="tree-title", id="tree-title")
        yield Static("", classes="tree-content", id="tree-content")

    def add_node(
        self,
        label: str,
        parent_id: int | None = None,
        confidence: float = 0.0,
        status: str = "pending"
    ) -> int:
        """添加思维节点"""
        node_id = self._next_id
        self._next_id += 1

        node = ThinkingNode(
            node_id=node_id,
            label=label,
            confidence=confidence,
            status=status,
            parent_id=parent_id,
        )

        self._nodes[node_id] = node

        if parent_id is not None and parent_id in self._nodes:
            self._nodes[parent_id].children.append(node_id)

        self._refresh_display()
        return node_id

    def update_node(
        self,
        node_id: int,
        status: str | None = None,
        confidence: float | None = None
    ) -> None:
        """更新节点状态"""
        if node_id in self._nodes:
            node = self._nodes[node_id]
            if status is not None:
                node.status = status
            if confidence is not None:
                node.confidence = confidence
            self._refresh_display()

    def _refresh_display(self) -> None:
        """刷新显示 (带节流控制)"""
        now = time.time()
        if now - self._last_refresh < self._refresh_interval:
            # 记录最后一次更新，稍后可能需要设置延时刷新以处理最后一条消息
            return

        try:
            content_widget = self.query_one("#tree-content", Static)
            lines = self._render_tree()
            content_widget.update('\n'.join(lines))
            self._last_refresh = now
        except Exception:
            pass

    def _render_tree(self) -> list[str]:
        """渲染思维树"""
        lines = []

        # 找到根节点
        roots = [n for n in self._nodes.values() if n.parent_id is None]

        for root in roots:
            self._render_node_recursive(root, lines, depth=0)

        return lines

    def _render_node_recursive(
        self,
        node: ThinkingNode,
        lines: list[str],
        depth: int = 0
    ) -> None:
        """递归渲染节点"""
        indent = "  " * depth

        # 连接符
        if depth > 0:
            connector = render_braille_connection(node.confidence)
        else:
            connector = "◆"

        # 状态图标
        status_icons = {
            "pending": "○",
            "running": "◉",
            "success": "✓",
            "error": "✗",
        }
        status_icon = status_icons.get(node.status, "·")

        # 置信度显示
        conf_pct = int(node.confidence * 100)

        # 进度条 (2x2 Block)
        progress_bar = render_block_progress(node.confidence, width=10)

        line = f"{indent}{connector} {status_icon} [{conf_pct}%] {node.label} {progress_bar}"
        lines.append(line)

        # 渲染子节点
        for child_id in node.children:
            if child_id in self._nodes:
                self._render_node_recursive(self._nodes[child_id], lines, depth + 1)
