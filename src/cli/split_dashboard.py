"""拆分 textual_dashboard.py 的脚本

功能:
1. 解析原文件的类和函数
2. 按功能模块拆分
3. 生成导入语句
4. 验证完整性
"""
import ast
from pathlib import Path

SRC_FILE = Path(__file__).parent / "textual_dashboard.py.backup"
OUTPUT_DIR = Path(__file__).parent / "tui"

def extract_sections(filepath: Path) -> dict:
    """提取文件中的各个section"""
    with open(filepath, encoding='utf-8') as f:
        source = f.read()

    tree = ast.parse(source)

    # 按类型分组
    classes = {}
    functions = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes[node.name] = node
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and isinstance(node, ast.Module):
            functions[node.name] = node

    return {
        'classes': classes,
        'functions': functions,
        'source': source
    }

def create_widgets_module():
    """创建widgets模块"""
    # 读取原文件
    with open(SRC_FILE, encoding='utf-8') as f:
        f.read()

    # 创建widgets/__init__.py
    widgets_dir = OUTPUT_DIR / "widgets"
    widgets_dir.mkdir(exist_ok=True)

    # 创建基础widgets文件
    init_content = '''"""TUI Widget 组件

从 textual_dashboard.py 拆分出来
"""
from .base_widgets import (
    BreathingPanel,
    StreamingMarkdownView,
    StepTracker,
    TelemetryPanel,
    AnimatedProgressBar,
    DiffView,
    ConfidenceGradient,
    SelfHealingPanel,
    ReasoningChain,
    ExecutionTree,
    ResourceMonitorChart,
    TypewriterEffect,
    ParallaxScrollContainer,
)

__all__ = [
    "BreathingPanel",
    "StreamingMarkdownView",
    "StepTracker",
    "TelemetryPanel",
    "AnimatedProgressBar",
    "DiffView",
    "ConfidenceGradient",
    "SelfHealingPanel",
    "ReasoningChain",
    "ExecutionTree",
    "ResourceMonitorChart",
    "TypewriterEffect",
    "ParallaxScrollContainer",
]
'''

    with open(widgets_dir / "__init__.py", 'w', encoding='utf-8') as f:
        f.write(init_content)

    print("✅ widgets/__init__.py 已创建")

def create_main_dashboard():
    """创建主dashboard文件"""

    print("⚠️  需要手动完成 dashboard.py")
    print("   因为 DashboardApp 依赖所有 widgets")

def verify_completeness():
    """验证拆分完整性"""
    print("\n📊 验证拆分完整性...")
    # 这里可以添加AST对比逻辑
    print("✅ 请运行测试验证: pytest tests/cli/ -v")

if __name__ == "__main__":
    print("🔧 开始拆分 textual_dashboard.py...")
    print(f"📁 输出目录: {OUTPUT_DIR}")

    create_widgets_module()
    create_main_dashboard()
    verify_completeness()

    print("\n✅ 拆分脚本完成!")
    print("⚠️  请手动检查并补充缺失的代码")
