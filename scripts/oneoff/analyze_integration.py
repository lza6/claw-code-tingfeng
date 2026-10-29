#!/usr/bin/env python3
"""
整合分析脚本 - claw-code-tingfeng vs oh-my-codex-main

分析两个项目的可整合内容，生成详细的整合建议。
"""

import os
import json
from pathlib import Path
from collections import defaultdict

def analyze_project_structure(project_path: Path, project_name: str) -> dict:
    """分析项目结构"""
    print(f"\n{'='*60}")
    print(f"📊 分析项目: {project_name}")
    print(f"{'='*60}")
    
    result = {
        "name": project_name,
        "path": str(project_path),
        "languages": [],
        "directories": {},
        "key_files": [],
        "tools_related": [],
        "config_related": [],
        "algorithms_related": []
    }
    
    if not project_path.exists():
        print(f"❌ 项目路径不存在: {project_path}")
        return result
    
    # 检测语言
    if (project_path / "Cargo.toml").exists():
        result["languages"].append("Rust")
    if (project_path / "package.json").exists():
        result["languages"].append("TypeScript/JavaScript")
    if (project_path / "pyproject.toml").exists() or (project_path / "setup.py").exists():
        result["languages"].append("Python")
    
    print(f"🔧 主要语言: {', '.join(result['languages'])}")
    
    # 分析目录结构
    top_level_dirs = [d for d in project_path.iterdir() if d.is_dir() and not d.name.startswith('.')]
    print(f"\n📁 顶级目录 ({len(top_level_dirs)} 个):")
    for d in sorted(top_level_dirs):
        file_count = len(list(d.rglob('*'))) if d.is_dir() else 0
        print(f"   - {d.name}/ ({file_count} 个文件)")
        result["directories"][d.name] = file_count
    
    # 查找关键文件
    key_patterns = [
        "**/tool*.py", "**/tool*.rs", "**/tool*.ts",
        "**/config*.py", "**/config*.rs", "**/config*.ts",
        "**/algorithm*.py", "**/algorithm*.rs",
        "**/utils*.py", "**/utils*.rs", "**/utils*.ts",
        "**/helper*.py", "**/helper*.rs",
    ]
    
    print(f"\n🔍 搜索关键文件...")
    for pattern in key_patterns[:3]:  # 只检查前3个模式
        matches = list(project_path.glob(pattern))
        if matches:
            category = "tools" if "tool" in pattern else "config" if "config" in pattern else "algorithms"
            result[f"{category}_related"].extend([str(m.relative_to(project_path)) for m in matches[:5]])
            print(f"   ✓ {pattern}: 找到 {len(matches)} 个文件")
    
    # 特殊目录检查
    special_dirs = {
        "tools": ["tools", "tools_runtime", "crates/*-tools"],
        "config": ["config", "settings", "conf"],
        "utils": ["utils", "helpers", "common"],
        "algorithms": ["algorithms", "algo", "core"]
    }
    
    print(f"\n📂 特殊目录检查:")
    for category, dir_names in special_dirs.items():
        found = [d.name for d in top_level_dirs if any(name in d.name.lower() for name in dir_names)]
        if found:
            print(f"   ✓ {category}: {', '.join(found)}")
    
    return result


def generate_integration_suggestions(clawd_analysis: dict, omx_analysis: dict) -> dict:
    """生成整合建议"""
    print(f"\n{'='*60}")
    print(f"💡 生成整合建议")
    print(f"{'='*60}")
    
    suggestions = {
        "high_priority": [],
        "medium_priority": [],
        "low_priority": [],
        "not_recommended": []
    }
    
    # 1. 工具类整合
    print(f"\n🔧 工具类整合分析:")
    clawd_tools = clawd_analysis.get("tools_related", [])
    omx_tools = omx_analysis.get("tools_related", [])
    
    if omx_tools:
        print(f"   oh-my-codex-main 有 {len(omx_tools)} 个工具相关文件")
        print(f"   ✅ 建议: 审查 oh-my-codex-main 的工具实现，提取通用工具")
        suggestions["high_priority"].append({
            "category": "工具类",
            "action": "审查并整合 oh-my-codex-main 的通用工具",
            "source": "oh-my-codex-main",
            "target": "claw-code-tingfeng/src/tools_runtime/",
            "reason": "避免重复造轮子，提升工具质量"
        })
    
    # 2. 配置优化
    print(f"\n⚙️  配置优化分析:")
    if omx_analysis["languages"] and "Rust" in omx_analysis["languages"]:
        print(f"   ⚠️  oh-my-codex-main 是 Rust 项目，配置系统不兼容")
        print(f"   ℹ️  建议: 仅参考设计理念，不要直接复制代码")
        suggestions["medium_priority"].append({
            "category": "配置优化",
            "action": "参考 oh-my-codex-main 的配置设计理念",
            "note": "Rust vs Python 语言不同，需重新实现",
            "reason": "学习优秀的配置管理模式"
        })
    
    # 3. 通用算法
    print(f"\n🧮 通用算法分析:")
    print(f"   需要深入检查 crates/ 和 src/ 目录")
    suggestions["medium_priority"].append({
        "category": "通用算法",
        "action": "检查 oh-my-codex-main/crates/ 中的核心算法",
        "focus": ["文本处理", "搜索算法", "缓存策略", "并发控制"],
        "reason": "Rust 实现可能更高效，可借鉴思路"
    })
    
    # 4. 核心业务逻辑
    print(f"\n🏗️  核心业务逻辑:")
    print(f"   ⚠️  谨慎整合 - 两个项目架构差异大")
    print(f"   - claw-code-tingfeng: Python AI Agent 框架")
    print(f"   - oh-my-codex-main: Rust/TS CLI 工具")
    suggestions["not_recommended"].append({
        "category": "核心业务逻辑",
        "action": "不建议直接整合核心逻辑",
        "reason": "技术栈和架构差异太大，整合成本高"
    })
    
    # 5. 文档和规范
    print(f"\n📚 文档和规范:")
    if (Path(omx_analysis["path"]) / "AGENTS.md").exists():
        print(f"   ✅ oh-my-codex-main 有 AGENTS.md")
        suggestions["high_priority"].append({
            "category": "文档规范",
            "action": "参考 oh-my-codex-main/AGENTS.md 改进本地文档",
            "source": "oh-my-codex-main/AGENTS.md",
            "reason": "提升项目文档质量"
        })
    
    return suggestions


def main():
    """主函数"""
    print("="*60)
    print("🔍 Claw-Code-Tingfeng vs Oh-My-Codex-Main 整合分析")
    print("="*60)
    
    # 项目路径
    current_dir = Path(__file__).parent
    clawd_path = current_dir
    omx_path = current_dir / "oh-my-codex-main"
    
    # 分析两个项目
    clawd_analysis = analyze_project_structure(clawd_path, "claw-code-tingfeng")
    omx_analysis = analyze_project_structure(omx_path, "oh-my-codex-main")
    
    # 生成整合建议
    suggestions = generate_integration_suggestions(clawd_analysis, omx_analysis)
    
    # 输出总结
    print(f"\n{'='*60}")
    print(f"📋 整合建议总结")
    print(f"{'='*60}")
    
    print(f"\n🔴 高优先级 ({len(suggestions['high_priority'])} 项):")
    for i, item in enumerate(suggestions['high_priority'], 1):
        print(f"   {i}. {item['action']}")
        print(f"      → {item.get('reason', '')}")
    
    print(f"\n🟡 中优先级 ({len(suggestions['medium_priority'])} 项):")
    for i, item in enumerate(suggestions['medium_priority'], 1):
        print(f"   {i}. {item['action']}")
        if 'note' in item:
            print(f"      ⚠️  {item['note']}")
    
    print(f"\n⚪ 低优先级 ({len(suggestions['low_priority'])} 项):")
    if suggestions['low_priority']:
        for i, item in enumerate(suggestions['low_priority'], 1):
            print(f"   {i}. {item['action']}")
    else:
        print(f"   (无)")
    
    print(f"\n❌ 不建议 ({len(suggestions['not_recommended'])} 项):")
    for i, item in enumerate(suggestions['not_recommended'], 1):
        print(f"   {i}. {item['action']}")
        print(f"      → {item.get('reason', '')}")
    
    # 保存报告
    report = {
        "claw_code_tingfeng": clawd_analysis,
        "oh_my_codex_main": omx_analysis,
        "integration_suggestions": suggestions,
        "generated_at": "2026-04-16"
    }
    
    report_path = current_dir / "INTEGRATION_ANALYSIS_REPORT.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 详细报告已保存到: {report_path}")
    print(f"\n{'='*60}")
    print("✅ 分析完成!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
