"""多模态视觉：把本地图片变成 LLM 消息里的 `image_url` 内容块

为什么单独一个模块：
- **能力判定**（`supports_vision`）与**块构造**（`build_image_blocks`）是两件不相关的事，
  都要能在不建 provider、不发请求的前提下单测；
- 回退策略要清楚：模型不支持视觉时不能硬塞内容块（provider 会 400），
  只能老实告诉用户"我看不到图"，这条边界必须在一个地方说清。

约定：
- 只接受**本地绝对路径**（桌面端把粘贴的图片落盘到 `<数据目录>/uploads/`）；
- 单图上限 `MAX_VISION_IMAGE_BYTES`（base64 会让体积膨胀 ~33%，太大直接不吃）；
- 认不出的扩展名按 `image/png` 处理（落盘时我们只写这几种）。
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: 单张图上限：2MB 原图 ≈ 2.7MB base64 ≈ 大量 token，再大就不划算了
MAX_VISION_IMAGE_BYTES = 2 * 1024 * 1024

#: 一次消息最多带几张图（防止用户一次粘 20 张把上下文撑爆）
MAX_IMAGES_PER_MESSAGE = 4

#: 扩展名 → MIME
_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

#: 已知支持图像输入的模型（子串匹配，小写）
#: 只放**真的能做视觉**的：这里判断错会导致 provider 400，用户体验比"看不到图"更糟。
VISION_MODEL_HINTS: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-5",
    "o3",
    "o4",
    "claude-3",
    "claude-4",
    "claude-sonnet",
    "claude-opus",
    "claude-haiku",
    "gemini",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "glm-4v",
    "glm-4.5v",
    "llava",
    "pixtral",
    "internvl",
    "step-1v",
    "step-1o",
    "doubao-vision",
    "yi-vision",
)


def supports_vision(model: str) -> bool:
    """这个模型能不能吃图片内容块

    优先级：`CLAWD_VISION` 环境变量（1/0 强制开/关）→ 模型名白名单。
    模型名认不出来时返回 False（保守）：宁可回退成"看不到图"，
    也不要把内容块塞给不支持的模型换来一个 400。
    """
    force = (os.environ.get("CLAWD_VISION") or "").strip().lower()
    if force in ("1", "true", "yes", "on"):
        return True
    if force in ("0", "false", "no", "off"):
        return False
    name = (model or "").strip().lower()
    if not name:
        return False
    return any(hint in name for hint in VISION_MODEL_HINTS)


def build_image_blocks(paths: list[str] | None) -> list[dict]:
    """把本地图片路径列表转成 OpenAI 兼容的 `image_url` 内容块

    读不到 / 太大 / 超过数量上限的一律**跳过并记 debug 日志**：
    附带图片是增强项，不能因为它把整条消息搞失败。
    """
    if not paths:
        return []
    blocks: list[dict] = []
    for raw in paths[:MAX_IMAGES_PER_MESSAGE]:
        try:
            path = Path(str(raw)).expanduser()
            if not path.is_absolute():
                logger.debug(f"跳过非绝对路径的图片: {raw}")
                continue
            if not path.is_file():
                logger.debug(f"跳过不存在的图片: {path}")
                continue
            size = path.stat().st_size
            if size <= 0 or size > MAX_VISION_IMAGE_BYTES:
                logger.debug(f"跳过体积不合适({size}B)的图片: {path.name}")
                continue
            data = path.read_bytes()
            mime = _MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")
            b64 = base64.b64encode(data).decode("ascii")
            blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        except OSError as exc:  # noqa: BLE001 — 单张图坏了不能挡住整条消息
            logger.debug(f"读取图片失败（已跳过）: {raw} -> {exc}")
    return blocks
