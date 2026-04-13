"""Image Utils — 图片工具（从 Aider utils.py 提取）

提供图片文件检测等功能。

用法:
    from src.utils.image_utils import is_image_file, IMAGE_EXTENSIONS

    if is_image_file("photo.jpg"):
        print("是图片文件")
"""
from __future__ import annotations

# 支持的图片扩展名
IMAGE_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tiff",
    ".webp",
    ".pdf",
}


def is_image_file(file_name: str) -> bool:
    """检查是否为图片文件

    参数:
        file_name: 文件名或路径

    Returns:
        是否为图片文件
    """
    return any(file_name.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)


def get_image_type(file_name: str) -> str | None:
    """获取图片类型

    参数:
        file_name: 文件名或路径

    Returns:
        图片类型或 None
    """
    for ext in IMAGE_EXTENSIONS:
        if file_name.lower().endswith(ext):
            return ext[1:]  # 去掉点
    return None


def is_pdf(file_name: str) -> bool:
    """检查是否为 PDF 文件

    参数:
        file_name: 文件名或路径

    Returns:
        是否为 PDF
    """
    return file_name.lower().endswith(".pdf")


def is_animated_image(file_name: str) -> bool:
    """检查是否为动态图片

    参数:
        file_name: 文件名或路径

    Returns:
        是否为动态图片（GIF）
    """
    return file_name.lower().endswith(".gif")


# 导出
__all__ = [
    "IMAGE_EXTENSIONS",
    "get_image_type",
    "is_animated_image",
    "is_image_file",
    "is_pdf",
]
