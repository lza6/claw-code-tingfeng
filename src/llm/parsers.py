"""LLM 转换与解析组件 - 移植自 Project B"""
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

# --- Thinking Tag Parser ---

class ContentType(Enum):
    """内容块类型"""
    TEXT = "text"
    THINKING = "thinking"

@dataclass
class ContentChunk:
    """解析后的内容块"""
    type: ContentType
    content: str

class ThinkTagParser:
    """
    流式 <think>...</think> 标签解析器。
    处理块边界处的碎片标签。
    """
    OPEN_TAG = "<think>"
    CLOSE_TAG = "</think>"
    OPEN_TAG_LEN = 7
    CLOSE_TAG_LEN = 8

    def __init__(self) -> None:
        self._buffer: str = ""
        self._in_think_tag: bool = False

    @property
    def in_think_mode(self) -> bool:
        return self._in_think_tag

    def feed(self, content: str) -> Iterator[ContentChunk]:
        self._buffer += content

        while self._buffer:
            prev_len = len(self._buffer)
            if not self._in_think_tag:
                chunk = self._parse_outside_think()
            else:
                chunk = self._parse_inside_think()

            if chunk:
                yield chunk
            elif len(self._buffer) == prev_len:
                break

    def _parse_outside_think(self) -> ContentChunk | None:
        think_start = self._buffer.find(self.OPEN_TAG)
        orphan_close = self._buffer.find(self.CLOSE_TAG)

        if orphan_close != -1 and (think_start == -1 or orphan_close < think_start):
            pre_orphan = self._buffer[:orphan_close]
            self._buffer = self._buffer[orphan_close + self.CLOSE_TAG_LEN :]
            if pre_orphan:
                return ContentChunk(ContentType.TEXT, pre_orphan)
            return None

        if think_start == -1:
            last_bracket = self._buffer.rfind("<")
            if last_bracket != -1:
                potential_tag = self._buffer[last_bracket:]
                tag_len = len(potential_tag)
                if (tag_len < self.OPEN_TAG_LEN and self.OPEN_TAG.startswith(potential_tag)) or \
                   (tag_len < self.CLOSE_TAG_LEN and self.CLOSE_TAG.startswith(potential_tag)):
                    emit = self._buffer[:last_bracket]
                    self._buffer = self._buffer[last_bracket:]
                    if emit:
                        return ContentChunk(ContentType.TEXT, emit)
                    return None
            emit = self._buffer
            self._buffer = ""
            if emit:
                return ContentChunk(ContentType.TEXT, emit)
            return None
        else:
            pre_think = self._buffer[:think_start]
            self._buffer = self._buffer[think_start + self.OPEN_TAG_LEN :]
            self._in_think_tag = True
            if pre_think:
                return ContentChunk(ContentType.TEXT, pre_think)
            return None

    def _parse_inside_think(self) -> ContentChunk | None:
        think_end = self._buffer.find(self.CLOSE_TAG)
        if think_end == -1:
            last_bracket = self._buffer.rfind("<")
            if last_bracket != -1 and len(self._buffer) - last_bracket < self.CLOSE_TAG_LEN:
                potential_tag = self._buffer[last_bracket:]
                if self.CLOSE_TAG.startswith(potential_tag):
                    emit = self._buffer[:last_bracket]
                    self._buffer = self._buffer[last_bracket:]
                    if emit:
                        return ContentChunk(ContentType.THINKING, emit)
                    return None
            emit = self._buffer
            self._buffer = ""
            if emit:
                return ContentChunk(ContentType.THINKING, emit)
            return None
        else:
            thinking_content = self._buffer[:think_end]
            self._buffer = self._buffer[think_end + self.CLOSE_TAG_LEN :]
            self._in_think_tag = False
            if thinking_content:
                return ContentChunk(ContentType.THINKING, thinking_content)
            return None

# --- Heuristic Tool Parser ---

class ParserState(Enum):
    TEXT = 1
    MATCHING_FUNCTION = 2
    PARSING_PARAMETERS = 3

class HeuristicToolParser:
    """
    启发式工具调用解析器。
    支持格式: ● <function=Name><parameter=key>value</parameter>
    """
    _FUNC_START_PATTERN = re.compile(r"●\s*<function=([^>]+)>")
    _PARAM_PATTERN = re.compile(r"<parameter=([^>]+)>(.*?)(?:</parameter>|$)", re.DOTALL)

    def __init__(self) -> None:
        self._state = ParserState.TEXT
        self._buffer = ""
        self._current_tool_id = None
        self._current_function_name = None
        self._current_parameters = {}

    def feed(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        self._buffer += text
        detected_tools = []
        filtered_output_parts = []

        while True:
            if self._state == ParserState.TEXT:
                if "●" in self._buffer:
                    idx = self._buffer.find("●")
                    filtered_output_parts.append(self._buffer[:idx])
                    self._buffer = self._buffer[idx:]
                    self._state = ParserState.MATCHING_FUNCTION
                else:
                    filtered_output_parts.append(self._buffer)
                    self._buffer = ""
                    break

            if self._state == ParserState.MATCHING_FUNCTION:
                match = self._FUNC_START_PATTERN.search(self._buffer)
                if match:
                    self._current_function_name = match.group(1).strip()
                    self._current_tool_id = f"toolu_heuristic_{uuid.uuid4().hex[:8]}"
                    self._current_parameters = {}
                    self._buffer = self._buffer[match.end() :]
                    self._state = ParserState.PARSING_PARAMETERS
                else:
                    if len(self._buffer) > 100:
                        filtered_output_parts.append(self._buffer[0])
                        self._buffer = self._buffer[1:]
                        self._state = ParserState.TEXT
                    else:
                        break

            if self._state == ParserState.PARSING_PARAMETERS:
                finished_tool_call = False
                while True:
                    param_match = self._PARAM_PATTERN.search(self._buffer)
                    if param_match and "</parameter>" in param_match.group(0):
                        pre_match_text = self._buffer[: param_match.start()]
                        if pre_match_text:
                            filtered_output_parts.append(pre_match_text)
                        key = param_match.group(1).strip()
                        val = param_match.group(2).strip()
                        self._current_parameters[key] = val
                        self._buffer = self._buffer[param_match.end() :]
                    else:
                        break

                if "●" in self._buffer:
                    idx = self._buffer.find("●")
                    if idx > 0:
                        filtered_output_parts.append(self._buffer[:idx])
                        self._buffer = self._buffer[idx:]
                    finished_tool_call = True
                elif len(self._buffer) > 0 and not self._buffer.strip().startswith("<"):
                    if "<parameter=" not in self._buffer:
                        filtered_output_parts.append(self._buffer)
                        self._buffer = ""
                        finished_tool_call = True

                if finished_tool_call:
                    detected_tools.append({
                        "type": "tool_use",
                        "id": self._current_tool_id,
                        "name": self._current_function_name,
                        "input": self._current_parameters,
                    })
                    self._state = ParserState.TEXT
                else:
                    break

        return "".join(filtered_output_parts), detected_tools
