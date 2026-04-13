"""
Sensitive Word Detection - 敏感词检测工具
基于 AC 自动机 (Aho-Corasick) 算法实现高效多模式匹配
时间复杂度: O(n + m + z)，其中 n 为文本长度，m 为模式串总长，z 为匹配数

整合自 new-api 项目，适配 claw-code 架构
"""

import hashlib
import re
import threading


class AhoCorasickNode:
    """AC 自动机节点"""
    __slots__ = ['children', 'depth', 'fail', 'output']

    def __init__(self):
        self.children: dict[str, AhoCorasickNode] = {}
        self.fail: AhoCorasickNode | None = None
        self.output: list[str] = []
        self.depth: int = 0


class AhoCorasickAutomaton:
    """
    Aho-Corasick 自动机实现
    用于高效的多模式字符串匹配
    """

    def __init__(self):
        self.root = AhoCorasickNode()
        self._built = False

    def build(self, patterns: list[str]) -> 'AhoCorasickAutomaton':
        """
        构建 AC 自动机

        Args:
            patterns: 模式串列表

        Returns:
            self
        """
        self.root = AhoCorasickNode()
        self._add_patterns(patterns)
        self._build_failure_function()
        self._built = True
        return self

    def _add_patterns(self, patterns: list[str]):
        """添加模式串到 Trie 树"""
        for pattern in patterns:
            pattern_lower = pattern.lower().strip()
            if not pattern_lower:
                continue

            node = self.root
            for char in pattern_lower:
                if char not in node.children:
                    new_node = AhoCorasickNode()
                    new_node.depth = node.depth + 1
                    node.children[char] = new_node
                node = node.children[char]

            node.output.append(pattern_lower)

    def _build_failure_function(self):
        """构建失败指针（BFS）"""
        queue = []

        # 根节点的子节点的 fail 指向根
        for char, node in self.root.children.items():
            node.fail = self.root
            queue.append(node)

        # BFS 构建 fail 指针
        head = 0
        while head < len(queue):
            current_node = queue[head]
            head += 1

            for char, next_node in current_node.children.items():
                queue.append(next_node)

                # 找到失败指针
                fail_node = current_node.fail
                while fail_node is not None and char not in fail_node.children:
                    fail_node = fail_node.fail

                next_node.fail = fail_node.children[char] if fail_node and char in fail_node.children else self.root

                # 合并输出
                next_node.output = next_node.output + next_node.fail.output

    def search(self, text: str, stop_immediately: bool = False) -> list[str]:
        """
        在文本中搜索匹配的模式串

        Args:
            text: 待搜索文本
            stop_immediately: 找到一个匹配后立即停止

        Returns:
            匹配到的模式串列表
        """
        if not self._built:
            return []

        text_lower = text.lower()
        matches = []
        node = self.root

        for char in text_lower:
            # 沿 fail 指针回溯直到找到匹配的子节点或到达根
            while node is not self.root and char not in node.children:
                node = node.fail

            if char in node.children:
                node = node.children[char]
            else:
                node = self.root

            # 收集输出
            if node.output:
                matches.extend(node.output)
                if stop_immediately and matches:
                    return matches

        return matches


class SensitiveWordCache:
    """敏感词自动机缓存"""

    _cache: dict[str, AhoCorasickAutomaton] = {}
    _lock = threading.RLock()
    _max_size = 100  # 最大缓存条目数

    @classmethod
    def get_or_build(cls, words: list[str]) -> AhoCorasickAutomaton | None:
        """
        获取或构建 AC 自动机

        Args:
            words: 敏感词列表

        Returns:
            AC 自动机实例
        """
        if not words:
            return None

        cache_key = cls._compute_cache_key(words)

        # 先尝试从缓存获取
        with cls._lock:
            if cache_key in cls._cache:
                return cls._cache[cache_key]

        # 构建新的自动机
        ac = AhoCorasickAutomaton().build(words)

        # 存入缓存
        with cls._lock:
            # 如果缓存已满，移除最旧的条目
            if len(cls._cache) >= cls._max_size:
                oldest_key = next(iter(cls._cache))
                del cls._cache[oldest_key]

            cls._cache[cache_key] = ac

        return ac

    @classmethod
    def _compute_cache_key(cls, words: list[str]) -> str:
        """计算缓存键"""
        normalized = sorted([w.lower().strip() for w in words if w.strip()])
        key_str = '|'.join(normalized)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    @classmethod
    def clear(cls):
        """清空缓存"""
        with cls._lock:
            cls._cache.clear()


class SensitiveWordService:
    """
    敏感词检测服务

    功能:
    - 敏感词检测
    - 敏感词替换
    - 支持消息列表检测（用于聊天场景）
    """

    def __init__(self):
        self._sensitive_words: list[str] = []
        self._replacement_text = "**###**"

    def set_sensitive_words(self, words: list[str]):
        """
        设置敏感词列表

        Args:
            words: 敏感词列表
        """
        self._sensitive_words = [w.lower().strip() for w in words if w.strip()]
        # 清空缓存
        SensitiveWordCache.clear()

    def get_sensitive_words(self) -> list[str]:
        """获取当前敏感词列表"""
        return self._sensitive_words.copy()

    def check_sensitive_words(self, text: str) -> tuple[bool, list[str]]:
        """
        检查文本是否包含敏感词

        Args:
            text: 待检查文本

        Returns:
            (是否包含敏感词, 敏感词列表)
        """
        if not self._sensitive_words or not text:
            return False, []

        ac = SensitiveWordCache.get_or_build(self._sensitive_words)
        if not ac:
            return False, []

        matches = ac.search(text, stop_immediately=True)
        if matches:
            # 去重
            unique_matches = list(dict.fromkeys(matches))
            return True, unique_matches

        return False, []

    def replace_sensitive_words(self, text: str) -> tuple[bool, list[str], str]:
        """
        替换文本中的敏感词

        Args:
            text: 待处理文本

        Returns:
            (是否包含敏感词, 敏感词列表, 替换后的文本)
        """
        if not self._sensitive_words or not text:
            return False, [], text

        ac = SensitiveWordCache.get_or_build(self._sensitive_words)
        if not ac:
            return False, [], text

        matches = ac.search(text, stop_immediately=False)
        if not matches:
            return False, [], text

        # 去重
        unique_matches = list(dict.fromkeys(matches))

        # 替换敏感词
        result = text
        for word in unique_matches:
            # 不区分大小写替换
            result = re.sub(re.escape(word), self._replacement_text, result, flags=re.IGNORECASE)

        return True, unique_matches, result

    def check_messages_sensitive(self, messages: list[dict]) -> tuple[bool, list[str]]:
        """
        检查消息列表是否包含敏感词

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]

        Returns:
            (是否包含敏感词, 敏感词列表)
        """
        if not messages:
            return False, []

        all_words = []
        for message in messages:
            content = message.get('content', '')

            # 处理多模态内容
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        text = item.get('text', '')
                        if text:
                            has_sensitive, words = self.check_sensitive_words(text)
                            all_words.extend(words)
                            if has_sensitive:
                                return True, list(dict.fromkeys(all_words))
            elif isinstance(content, str) and content:
                has_sensitive, words = self.check_sensitive_words(content)
                all_words.extend(words)
                if has_sensitive:
                    return True, list(dict.fromkeys(all_words))

        return bool(all_words), list(dict.fromkeys(all_words))


# 全局单例实例
_sensitive_word_service = SensitiveWordService()


def get_sensitive_word_service() -> SensitiveWordService:
    """获取敏感词检测服务单例"""
    return _sensitive_word_service


def check_sensitive_words(text: str) -> tuple[bool, list[str]]:
    """
    快捷函数：检查敏感词

    Args:
        text: 待检查文本

    Returns:
        (是否包含敏感词, 敏感词列表)
    """
    return _sensitive_word_service.check_sensitive_words(text)


def replace_sensitive_words(text: str) -> tuple[bool, list[str], str]:
    """
    快捷函数：替换敏感词

    Args:
        text: 待处理文本

    Returns:
        (是否包含敏感词, 敏感词列表, 替换后的文本)
    """
    return _sensitive_word_service.replace_sensitive_words(text)


def set_sensitive_words(words: list[str]):
    """
    快捷函数：设置敏感词

    Args:
        words: 敏感词列表
    """
    _sensitive_word_service.set_sensitive_words(words)
