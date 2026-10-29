#!/usr/bin/env python3
"""
检查 claw-code-tingfeng 项目的工具文件结构
"""

import os
from pathlib import Path

def check_tools_structure():
    """检查工具文件的组织结构"""
    project_root = Path(__file__).parent
    
    print("=" * 60)
    print("🔍 Claw-Code-Tingfeng 项目工具文件检查")
    print("=" * 60)
    
    # 检查 tools_runtime 目录
    tools_dir = project_root / "src" / "tools_runtime"
    
    if not tools_dir.exists():
        print(f"❌ tools_runtime 目录不存在: {tools_dir}")
        return
    
    print(f"\n✅ tools_runtime 目录存在: {tools_dir}")
    
    # 统计 Python 文件
    py_files = list(tools_dir.glob("*.py"))
    print(f"\n📊 工具文件统计:")
    print(f"   - Python 文件数量: {len(py_files)}")
    
    # 按功能分类
    categories = {
        "基础工具": ["base.py", "types.py", "tool_interface.py", "registry.py"],
        "文件操作": ["file_read_tool.py", "file_edit_tool.py", "file_processor.py"],
        "代码编辑": ["search_replace.py", "edit_parser.py", "udiff_tool.py", "udiff_parser.py"],
        "搜索工具": ["grep_tool.py", "glob_tool.py", "symbol_find_tool.py", "search_v2_tool.py"],
        "Bash 相关": ["bash_tool.py", "bash_executor.py", "bash_security.py", "bash_constants.py"],
        "Lint 工具": ["linter.py", "linter_linter.py", "linter_python.py", "linter_tree_sitter.py"],
        "其他工具": ["clipboard_tool.py", "scrape_tool.py", "voice_tool.py", "watch_tool.py"],
    }
    
    print(f"\n📁 工具分类:")
    for category, files in categories.items():
        found = [f for f in files if (tools_dir / f).exists()]
        if found:
            print(f"   ✓ {category}: {len(found)}/{len(files)} 个文件")
    
    # 检查子目录
    subdirs = [d for d in tools_dir.iterdir() if d.is_dir() and not d.name.startswith("__")]
    if subdirs:
        print(f"\n📂 子目录:")
        for subdir in subdirs:
            files_count = len(list(subdir.glob("*.py")))
            print(f"   - {subdir.name}/: {files_count} 个 Python 文件")
    
    # 检查 __init__.py 导出
    init_file = tools_dir / "__init__.py"
    if init_file.exists():
        content = init_file.read_text(encoding='utf-8')
        if "__all__" in content:
            print(f"\n✅ __init__.py 包含 __all__ 导出")
        else:
            print(f"\n⚠️  __init__.py 未定义 __all__")
    
    print("\n" + "=" * 60)
    print("💡 建议:")
    print("   1. 工具文件组织良好,位于 src/tools_runtime/")
    print("   2. 搜索时应使用: src/tools_runtime/*.py")
    print("   3. 避免使用: src/**/tool*.py (可能找不到文件)")
    print("=" * 60)

if __name__ == "__main__":
    check_tools_structure()
