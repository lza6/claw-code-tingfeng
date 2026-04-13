"""
增强 Token 计数器 - 整合自 New-API
支持多种模型的精确 Token 计算，包含多模态（文本/图片/音频/视频）
整合了 new-api 项目的 tile/patch 两种图片算法和多媒体计数
"""

import base64
import math
from typing import Any

import tiktoken
from loguru import logger

# Token 编码器缓存（改进版：使用模型到编码器的精确映射）
_encoder_cache: dict[str, tiktoken.Encoding] = {}

# 模型到编码器的映射表
_ENCODING_MAP = {
    "gpt-4": "cl100k_base",
    "gpt-4-32k": "cl100k_base",
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "gpt-3.5-turbo-16k": "cl100k_base",
    "gpt-3.5-turbo-instruct": "cl100k_base",
    "text-embedding-ada-002": "cl100k_base",
    "text-embedding-3-small": "cl100k_base",
    "text-embedding-3-large": "cl100k_base",
    "claude-3-opus": "cl100k_base",
    "claude-3-sonnet": "cl100k_base",
    "claude-3-haiku": "cl100k_base",
    "claude-3.5-sonnet": "cl100k_base",
}


# ==================== 文本 Token 计算 ====================


def get_encoder(model: str = "gpt-4") -> tiktoken.Encoding:
    """
    获取 tiktoken 编码器（带缓存）

    Args:
        model: 模型名称

    Returns:
        tiktoken.Encoding: 编码器实例
    """
    if model in _encoder_cache:
        return _encoder_cache[model]

    # 获取 encoding name
    encoding_name = "cl100k_base"  # 默认值

    # 精确匹配或前缀匹配
    for key in _ENCODING_MAP:
        if model == key or model.startswith(key):
            encoding_name = _ENCODING_MAP[key]
            break

    try:
        encoder = tiktoken.get_encoding(encoding_name)
    except Exception as e:
        logger.warning(f"无法加载 {model} 的编码器 ({encoding_name}): {e}，使用 cl100k_base")
        encoder = tiktoken.get_encoding("cl100k_base")

    _encoder_cache[model] = encoder
    return encoder


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    计算文本的 token 数量

    Args:
        text: 要计算的文本
        model: 模型名称

    Returns:
        int: token 数量
    """
    try:
        encoder = get_encoder(model)
        return len(encoder.encode(text))
    except Exception as e:
        logger.error(f"Token 计数失败: {e}")
        # 回退到估算
        return estimate_tokens(text)


def count_message_tokens(
    messages: list[dict[str, str]],
    model: str = "gpt-4"
) -> int:
    """
    计算聊天消息的 token 数量（包含 OpenAI 格式的消息开销）

    Args:
        messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
        model: 模型名称

    Returns:
        int: 总 token 数量
    """
    try:
        encoder = get_encoder(model)

        # 每条消息的基础 token 开销
        tokens_per_message = 3  # 每条消息的固定开销
        tokens_per_name = 1  # 角色名的开销

        num_tokens = 0
        for message in messages:
            num_tokens += tokens_per_message
            for key, value in message.items():
                if isinstance(value, str):
                    num_tokens += len(encoder.encode(value))
                if key == "name":
                    num_tokens += tokens_per_name

        # 回复的基础开销
        num_tokens += 3  # 每条回复的固定开销
        return num_tokens
    except Exception as e:
        logger.error(f"消息 Token 计数失败: {e}")
        # 回退到简单计数
        total_text = " ".join([msg.get("content", "") for msg in messages])
        return count_tokens(total_text, model)


def estimate_tokens(text: str) -> int:
    """
    快速估算 token 数量（不使用 tiktoken，适合大量文本）
    基于经验法则：英文约 1 token = 4 字符，中文约 1 token = 1.5 字符

    Args:
        text: 要估算的文本

    Returns:
        int: 估算的 token 数量
    """
    if not text:
        return 0

    # 统计中文字符
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # 统计英文字符
    english_chars = len(text) - chinese_chars

    # 估算 token 数
    return chinese_chars // 2 + english_chars // 4


def get_model_context_window(model: str) -> int:
    """
    获取模型的上下文窗口大小

    Args:
        model: 模型名称

    Returns:
        int: 上下文窗口大小（tokens）
    """
    context_windows = {
        "gpt-4": 8192,
        "gpt-4-32k": 32768,
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-3.5-turbo": 16385,
        "gpt-3.5-turbo-16k": 16385,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-haiku": 200000,
        "claude-3.5-sonnet": 200000,
        "gemini-pro": 32768,
        "gemini-1.5-pro": 1000000,
    }

    # 前缀匹配
    for model_prefix, context_size in context_windows.items():
        if model_prefix in model.lower():
            return context_size

    # 默认值
    return 8192


# ==================== 多媒体 Token 计算 ====================


def count_image_tokens(
    width: int,
    height: int,
    detail: str = "auto"
) -> int:
    """
    计算图片的 token 数量（用于 GPT-4 Vision）

    Args:
        width: 图片宽度
        height: 图片高度
        detail: 图片详细程度 (low, high, auto)

    Returns:
        int: 图片 token 数量
    """
    if detail == "low":
        return 85

    # 高清模式：先缩放到 2048x2048，然后按 512 像素块计算
    if max(width, height) > 2048:
        scale = 2048 / max(width, height)
        width = int(width * scale)
        height = int(height * scale)

    # 确保短边不超过 768
    if min(width, height) > 768:
        scale = 768 / min(width, height)
        width = int(width * scale)
        height = int(height * scale)

    # 计算 512 像素块数量
    tiles = (width + 511) // 512 * (height + 511) // 512

    # 每个 tile 170 tokens + 基础 85 tokens
    return tiles * 170 + 85


def count_image_tokens_advanced(
    width: int,
    height: int,
    model: str = "gpt-4o",
    detail: str = "auto"
) -> int:
    """
    计算图片的 token 数量（高级版，支持多种模型的 tile 和 patch 两种算法）

    Args:
        width: 图片宽度
        height: 图片高度
        model: 模型名称
        detail: 图片详细程度 (low, high, auto)

    Returns:
        int: 图片 token 数量
    """
    model_lower = model.lower()

    # 特殊模型处理
    if model_lower.startswith("glm-4"):
        return 1047

    # 基础 tile 参数
    base_tokens = 85
    tile_tokens = 170
    is_patch_based = False
    multiplier = 1.0

    # Patch-based 模型（32x32 patches）
    if "gpt-4.1-mini" in model_lower:
        is_patch_based = True
        multiplier = 1.62
    elif "gpt-4.1-nano" in model_lower:
        is_patch_based = True
        multiplier = 2.46
    elif model_lower.startswith("o4-mini"):
        is_patch_based = True
        multiplier = 1.72
    elif model_lower.startswith("gpt-5-mini"):
        is_patch_based = True
        multiplier = 1.62
    elif model_lower.startswith("gpt-5-nano"):
        is_patch_based = True
        multiplier = 2.46

    # Tile-based 模型
    if not is_patch_based:
        if model_lower.startswith("gpt-4o-mini"):
            base_tokens = 2833
            tile_tokens = 5667
        elif (model_lower.startswith("gpt-5-chat-latest") or
              (model_lower.startswith("gpt-5") and "mini" not in model_lower and "nano" not in model_lower)):
            base_tokens = 70
            tile_tokens = 140
        elif (model_lower.startswith("o1") or
              model_lower.startswith("o3") or
              "o1-pro" in model_lower):
            base_tokens = 75
            tile_tokens = 150
        elif "computer-use-preview" in model_lower:
            base_tokens = 65
            tile_tokens = 129
        elif "4.1" in model_lower or "4o" in model_lower or "4.5" in model_lower:
            base_tokens = 85
            tile_tokens = 170

    # Low detail 模式
    if detail == "low" and not is_patch_based:
        return base_tokens

    # Patch-based 计算
    if is_patch_based:
        def ceil_div(a, b):
            return (a + b - 1) // b
        raw_patches_w = ceil_div(width, 32)
        raw_patches_h = ceil_div(height, 32)
        raw_patches = raw_patches_w * raw_patches_h

        if raw_patches > 1536:
            # 缩放至 1536 patches 以内
            area = width * height
            r = math.sqrt((32 * 32 * 1536) / area)
            w_scaled = width * r
            h_scaled = height * r

            adj_w = math.floor(w_scaled / 32.0) / (w_scaled / 32.0)
            adj_h = math.floor(h_scaled / 32.0) / (h_scaled / 32.0)
            adj = min(adj_w, adj_h)

            if not math.isnan(adj) and adj > 0:
                r = r * adj

            w_scaled = width * r
            h_scaled = height * r
            patches_w = math.ceil(w_scaled / 32.0)
            patches_h = math.ceil(h_scaled / 32.0)
            image_tokens = int(patches_w * patches_h)
            image_tokens = min(image_tokens, 1536)

            return round(image_tokens * multiplier)
        else:
            return round(raw_patches * multiplier)

    # Tile-based 计算（4o/4.1/4.5/o1/o3 等）
    # 步骤 1: 适配到 2048x2048 以内
    max_side = max(width, height)
    fit_scale = 1.0
    if max_side > 2048:
        fit_scale = max_side / 2048.0

    fit_w = round(width / fit_scale)
    fit_h = round(height / fit_scale)

    # 步骤 2: 缩放使短边为 768
    min_side = min(fit_w, fit_h)
    if min_side == 0:
        return base_tokens

    short_scale = 768.0 / min_side
    final_w = round(fit_w * short_scale)
    final_h = round(fit_h * short_scale)

    # 计算 512px tiles
    tiles_w = (final_w + 512 - 1) // 512
    tiles_h = (final_h + 512 - 1) // 512
    tiles = tiles_w * tiles_h

    return tiles * tile_tokens + base_tokens


def count_audio_token_input(audio_base64: str, audio_format: str = "mp3") -> int:
    """
    计算输入音频的 token 数量
    基于音频时长计算，1 分钟约 1000 tokens

    Args:
        audio_base64: Base64 编码的音频数据
        audio_format: 音频格式 (mp3, wav, flac 等)

    Returns:
        int: 音频 token 数量（估算值）
    """
    if not audio_base64:
        return 0

    # 简化实现：根据数据大小估算时长
    # 实际应用中应该解析音频头信息获取准确时长
    try:
        audio_bytes = len(base64.b64decode(audio_base64))
        # 假设 128kbps 码率，约 16000 bytes/秒
        duration_seconds = audio_bytes / 16000
        # 1 分钟 = 1000 tokens
        return math.ceil(duration_seconds / 60.0 * 1000)
    except Exception:
        # 解码失败，返回默认值
        return 256


def count_audio_token_output(audio_base64: str, audio_format: str = "mp3") -> int:
    """
    计算输出音频的 token 数量
    基于音频时长计算

    Args:
        audio_base64: Base64 编码的音频数据
        audio_format: 音频格式

    Returns:
        int: 音频 token 数量（估算值）
    """
    if not audio_base64:
        return 0

    try:
        audio_bytes = len(base64.b64decode(audio_base64))
        duration_seconds = audio_bytes / 16000
        # 输出音频定价不同
        return math.ceil(duration_seconds / 60.0 * 2000)
    except Exception:
        return 256


def count_video_token(duration_seconds: int = 0) -> int:
    """
    计算视频的 token 数量

    Args:
        duration_seconds: 视频时长（秒）

    Returns:
        int: 视频 token 数量
    """
    if duration_seconds > 0:
        # 根据时长计算
        return duration_seconds * 137  # 约每秒 137 tokens
    # 默认值
    return 8192


def count_file_token(file_type: str = "unknown") -> int:
    """
    计算文件的 token 数量

    Args:
        file_type: 文件类型 (image, audio, video, file)

    Returns:
        int: 文件 token 数量
    """
    token_map = {
        "image": 520,      # 非 OpenAI 模型的图片
        "audio": 256,      # 音频
        "video": 8192,     # 视频
        "file": 4096,      # 普通文件
        "unknown": 4096,   # 未知类型
    }
    return token_map.get(file_type, 4096)


def count_message_tokens_advanced(
    messages: list[dict[str, Any]],
    model: str = "gpt-4",
    include_media: bool = True
) -> int:
    """
    计算聊天消息的 token 数量（包含多媒体内容）

    Args:
        messages: 消息列表
        model: 模型名称
        include_media: 是否计算多媒体内容

    Returns:
        int: 总 token 数量
    """
    try:
        encoder = get_encoder(model)

        tokens_per_message = 3
        tokens_per_name = 1

        num_tokens = 0
        for message in messages:
            num_tokens += tokens_per_message

            # 角色名
            if "role" in message:
                num_tokens += len(encoder.encode(message["role"]))
                num_tokens += tokens_per_name

            # 内容
            content = message.get("content", "")
            if isinstance(content, str):
                num_tokens += len(encoder.encode(content))
            elif isinstance(content, list):
                # 多模态内容
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text = item.get("text", "")
                            num_tokens += len(encoder.encode(text))
                        elif item.get("type") == "image_url" and include_media:
                            image_url = item.get("image_url", {})
                            detail = image_url.get("detail", "auto")
                            # 默认图片尺寸估算
                            num_tokens += count_image_tokens(1024, 1024, detail)

            # 工具调用
            if "tool_calls" in message:
                for tool_call in message["tool_calls"]:
                    if "function" in tool_call:
                        func = tool_call["function"]
                        num_tokens += len(encoder.encode(func.get("name", "")))
                        num_tokens += len(encoder.encode(func.get("arguments", "")))
                    num_tokens += 8  # 工具调用开销

            # 名字
            if "name" in message:
                num_tokens += tokens_per_name

        # 回复基础开销
        num_tokens += 3

        return num_tokens
    except Exception as e:
        logger.error(f"高级消息 Token 计数失败: {e}")
        # 回退到基础计数
        total_text = " ".join([
            msg.get("content", "") if isinstance(msg.get("content"), str) else ""
            for msg in messages
        ])
        return count_tokens(total_text, model)
