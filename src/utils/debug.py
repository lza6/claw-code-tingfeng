"""Dump utility — 从 Aider dump.py 移植

调试辅助工具，用于打印变量值（带变量名自动检测）。

用法:
    from src.utils.debug import dump

    x = {'a': 1}
    dump(x)  # 输出: x: {'a': 1}
"""
from __future__ import annotations

import json
import traceback


def cvt(s: object) -> str:
    """将值转换为字符串

    Args:
        s: 任意值

    Returns:
        字符串表示
    """
    if isinstance(s, str):
        return s
    try:
        return json.dumps(s, indent=4)
    except TypeError:
        return str(s)


def dump(*vals: object) -> None:
    """打印变量值（自动检测变量名）

    从调用栈获取变量名并打印。

    用法:
        x = 42
        dump(x)  # 输出: x: 42

        data = {'a': 1}
        dump(data)  # 输出: data: {"a": 1}
    """
    # 获取调用栈
    stack = traceback.extract_stack()
    vars_str = stack[-2][3]

    # 去除 dump() 调用部分
    vars_str = "(".join(vars_str.split("(")[1:])
    vars_str = ")".join(vars_str.split(")")[:-1])

    # 转换值
    vals_converted = [cvt(v) for v in vals]

    # 检查是否有换行符
    has_newline = sum(1 for v in vals_converted if "\n" in v)

    if has_newline:
        print(f"{vars_str}:")
        print(", ".join(vals_converted))
    else:
        print(f"{vars_str}:", ", ".join(vals_converted))


def dump_json(obj: object, indent: int = 2) -> str:
    """将对象转换为格式化的 JSON 字符串

    Args:
        obj: 任意可序列化对象
        indent: 缩进空格数

    Returns:
        格式化的 JSON 字符串
    """
    return json.dumps(obj, indent=indent, ensure_ascii=False)


def dump_as_table(data: list[dict], headers: list[str] | None = None) -> None:
    """将数据以表格形式打印

    Args:
        data: 字典列表
        headers: 可选的表头列表
    """
    if not data:
        print("(empty)")
        return

    # 自动提取表头
    if headers is None:
        headers = list(data[0].keys())

    # 计算每列宽度
    col_widths = {}
    for h in headers:
        col_widths[h] = len(str(h))
        for row in data:
            val = str(row.get(h, ""))
            col_widths[h] = max(col_widths[h], len(val))

    # 打印表头
    header_line = " | ".join(str(h).ljust(col_widths[h]) for h in headers)
    print(header_line)
    print("-" * len(header_line))

    # 打印数据行
    for row in data:
        row_line = " | ".join(str(row.get(h, "")).ljust(col_widths[h]) for h in headers)
        print(row_line)


__all__ = ["cvt", "dump", "dump_as_table", "dump_json"]
