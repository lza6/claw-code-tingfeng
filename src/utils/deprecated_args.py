"""Deprecated Args — 处理过时的命令行参数（从 Aider 移植）

提供对旧版本参数的兼容性检查和警告。
"""
from __future__ import annotations


def is_deprecated_model_arg(arg: str) -> bool:
    """检查是否为过时的模型快捷参数"""
    deprecated_args = {
        "--opus",
        "--sonnet",
        "--haiku",
        "--gpt-4",
        "--gpt-3.5",
    }
    return arg in deprecated_args


def get_deprecated_message(arg: str) -> str:
    """获取过时参数的提示信息"""
    return f"参数 '{arg}' 已过时，请使用 '--model <model_name>' 代替。"


def check_deprecated_args(args: list[str]) -> list[str]:
    """检查并清理过时参数"""
    cleaned_args = []
    for arg in args:
        if is_deprecated_model_arg(arg):
            # 记录日志或打印警告 (这里简单处理)
            pass
        else:
            cleaned_args.append(arg)
    return cleaned_args


# 导出
__all__ = [
    "check_deprecated_args",
    "get_deprecated_message",
    "is_deprecated_model_arg",
]
