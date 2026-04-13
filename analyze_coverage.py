#!/usr/bin/env python3
"""Analyze test coverage and identify modules needing more tests."""

import json
from pathlib import Path

def analyze_coverage():
    """Parse coverage status.json and identify low-coverage modules."""
    
    # Read coverage data
    status_file = Path("htmlcov/status.json")
    if not status_file.exists():
        print("❌ Coverage report not found. Run: pytest --cov=src --cov-report=html")
        return
    
    with open(status_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    files = data.get("files", {})
    
    # Analyze each module
    module_stats = {}
    
    for file_key, file_data in files.items():
        index = file_data.get("index", {})
        nums = index.get("nums", {})
        
        filepath = index.get("file", "")
        statements = nums.get("n_statements", 0)
        missing = nums.get("n_missing", 0)
        
        if statements == 0:
            continue
        
        coverage_pct = ((statements - missing) / statements) * 100
        
        # Group by module
        parts = filepath.split("\\")
        if len(parts) >= 2:
            module = parts[1]  # e.g., "agent", "core", "workflow"
            if module not in module_stats:
                module_stats[module] = {
                    "total_statements": 0,
                    "total_missing": 0,
                    "files": []
                }
            
            module_stats[module]["total_statements"] += statements
            module_stats[module]["total_missing"] += missing
            module_stats[module]["files"].append({
                "path": filepath,
                "statements": statements,
                "missing": missing,
                "coverage": coverage_pct
            })
    
    # Calculate module-level coverage
    print("=" * 80)
    print("📊 TEST COVERAGE ANALYSIS BY MODULE")
    print("=" * 80)
    print()
    
    for module_name, stats in sorted(module_stats.items()):
        total_stmt = stats["total_statements"]
        total_miss = stats["total_missing"]
        coverage = ((total_stmt - total_miss) / total_stmt * 100) if total_stmt > 0 else 0
        
        # Determine status
        if coverage >= 90:
            status = "✅ EXCELLENT"
        elif coverage >= 75:
            status = "⚠️  GOOD"
        elif coverage >= 50:
            status = "❌ NEEDS IMPROVEMENT"
        else:
            status = "🔴 CRITICAL"
        
        print(f"{module_name:25s} | Coverage: {coverage:6.1f}% | Statements: {total_stmt:4d} | Missing: {total_miss:4d} | {status}")
    
    print()
    print("=" * 80)
    print("🎯 PRIORITY TARGETS FOR SPRINT 2 (Coverage < 50%)")
    print("=" * 80)
    print()
    
    priority_modules = []
    for module_name, stats in sorted(module_stats.items()):
        total_stmt = stats["total_statements"]
        total_miss = stats["total_missing"]
        coverage = ((total_stmt - total_miss) / total_stmt * 100) if total_stmt > 0 else 0
        
        if coverage < 50:
            priority_modules.append((module_name, coverage, total_stmt))
    
    for module_name, coverage, total_stmt in sorted(priority_modules, key=lambda x: x[1]):
        print(f"  • {module_name:25s} ({coverage:.1f}% coverage, {total_stmt} statements)")
    
    print()
    print("=" * 80)
    print("📋 LOW-COVERAGE FILES (< 30% coverage)")
    print("=" * 80)
    print()
    
    low_coverage_files = []
    for file_key, file_data in files.items():
        index = file_data.get("index", {})
        nums = index.get("nums", {})
        
        filepath = index.get("file", "")
        statements = nums.get("n_statements", 0)
        missing = nums.get("n_missing", 0)
        
        if statements == 0:
            continue
        
        coverage_pct = ((statements - missing) / statements) * 100
        
        if coverage_pct < 30 and statements > 50:  # Skip small files
            low_coverage_files.append((filepath, coverage_pct, statements, missing))
    
    # Sort by coverage (ascending)
    for filepath, coverage, stmt, miss in sorted(low_coverage_files, key=lambda x: x[1])[:20]:
        print(f"  • {filepath:60s} | {coverage:5.1f}% | {stmt:4d} stmts | {miss:4d} missing")
    
    print()
    print(f"Total files analyzed: {len(files)}")
    print(f"Files with < 30% coverage: {len(low_coverage_files)}")
    print()

if __name__ == "__main__":
    analyze_coverage()
