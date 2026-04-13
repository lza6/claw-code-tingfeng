#!/usr/bin/env python3
"""
ClawGod 整合 - REPL 快速集成脚本

此脚本自动将命令注册表集成到 REPL 中。
运行前请备份 src/cli/repl.py 文件！

用法:
    python integrate_command_registry.py
"""
import re
from pathlib import Path

def backup_file(file_path: Path) -> Path:
    """创建文件备份"""
    backup_path = file_path.with_suffix('.py.bak')
    if not backup_path.exists():
        import shutil
        shutil.copy2(file_path, backup_path)
        print(f"✅ 已创建备份: {backup_path}")
    else:
        print(f"⚠️  备份已存在: {backup_path}")
    return backup_path

def integrate_command_registry(repl_path: Path):
    """将命令注册表集成到 REPL"""
    
    print("🔧 开始集成命令注册表到 REPL...")
    print(f"📄 目标文件: {repl_path}")
    
    # 读取文件
    with open(repl_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. 添加导入语句（在文件顶部）
    import_section_end = content.find('from .cli_handlers import get_command_handler')
    if import_section_end == -1:
        print("❌ 未找到导入区域，请手动添加以下导入:")
        print('   from .command_registry import command_registry')
        return False
    
    # 检查是否已经添加
    if 'from .command_registry import command_registry' in content:
        print("✅ 导入语句已存在")
    else:
        # 在第一个 from 导入之前添加
        first_import = content.find('from ')
        if first_import != -1:
            new_import = "from .command_registry import command_registry\n"
            content = content[:first_import] + new_import + content[first_import:]
            print("✅ 已添加导入语句")
    
    # 2. 在 ReplSession.__init__ 中初始化命令注册表
    init_pattern = r'(def __init__\([^)]+\)[\s\S]*?)(self\._loop = asyncio\.new_event_loop\(\))'
    init_match = re.search(init_pattern, content)
    
    if init_match:
        init_code = init_match.group(0)
        if 'command_registry.initialize_builtin_commands()' in init_code:
            print("✅ 命令注册表初始化已存在")
        else:
            # 在 _loop 初始化之后添加
            insert_pos = init_match.end()
            initialization_code = '\n        # Initialize command registry (ClawGod integration)\n        command_registry.initialize_builtin_commands()\n'
            content = content[:insert_pos] + initialization_code + content[insert_pos:]
            print("✅ 已添加命令注册表初始化")
    else:
        print("⚠️  未找到 __init__ 方法，请手动添加:")
        print('   command_registry.initialize_builtin_commands()')
    
    # 3. 替换 _handle_builtin 方法
    handle_builtin_pattern = r'(def _handle_builtin\(self, cmd: str\) -> bool:[\s\S]*?)(return True)'
    handle_match = re.search(handle_builtin_pattern, content, re.MULTILINE)
    
    if handle_match:
        old_method = handle_match.group(0)
        
        # 新的实现
        new_method = '''def _handle_builtin(self, cmd: str) -> bool:
        """处理内置命令（使用命令注册表 - ClawGod 整合）"""
        handler = command_registry.find(cmd)
        
        if handler:
            # 如果命令需要引擎，先初始化
            if handler.requires_engine:
                self._init_engine()
            
            # 执行命令
            try:
                # 传递 engine 如果需要
                args = self.engine if handler.requires_engine else None
                result = handler.handler(args)
                
                # 处理返回值
                if isinstance(result, bool):
                    return result  # False means exit
                return True
            except Exception as e:
                _print(f"  {status_fail(f'命令执行失败: {e}')}")
                return True
        
        # 未知命令
        _print(f'  {status_warn(f"未知命令: {cmd}")}')
        _print(f'  输入 /help 查看可用命令')
        return True'''
        
        content = content.replace(old_method, new_method)
        print("✅ 已替换 _handle_builtin 方法")
    else:
        print("⚠️  未找到 _handle_builtin 方法，请手动替换")
        print("   参考 CLAWGOD_USAGE_EXAMPLES.md 第5节")
    
    # 写回文件
    with open(repl_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("\n✅ 集成完成！")
    print("\n📝 下一步:")
    print("   1. 运行测试: python -m pytest tests/ -v")
    print("   2. 启动 REPL: python -m src.main chat")
    print("   3. 测试命令: /help, /doctor, /features")
    print("\n⚠️  如有问题，可恢复备份:")
    print(f"   cp {repl_path}.bak {repl_path}")
    
    return True

if __name__ == '__main__':
    repl_path = Path(__file__).parent / 'src' / 'cli' / 'repl.py'
    
    if not repl_path.exists():
        print(f"❌ 文件不存在: {repl_path}")
        exit(1)
    
    # 创建备份
    backup_file(repl_path)
    
    # 执行集成
    success = integrate_command_registry(repl_path)
    
    if success:
        print("\n🎉 成功！现在可以测试新功能了。")
    else:
        print("\n⚠️  集成未完成，请查看上述提示手动操作。")
        exit(1)
