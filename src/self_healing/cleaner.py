"""Anti-Slop Cleaner — 代码去腐化工具 (汲取自 Project B)

核心目标：自动检测并切除 AI 生成代码中的"赘肉"，保持项目极简。
"""
from __future__ import annotations

import re
from pathlib import Path


class SlopCleaner:
    # 典型的 AI 废话模式
    SLOP_PATTERNS = [
        r'# This function .* handles the logic for .*',  # 描述性的废话注释
        r'"""\s*Implementation of .*\s*"""',              # 无实质意义的 docstring
        r'# Helper function to .*',                      # 自明性的注释
        r'# Import required libraries',                  # 导航式废话
        r'# Define (the )?variables?',                    # 无意义的变量定义说明
        r'# Initialize (the )?.*',                        # 初始化说明
        r'# Return (the )?result',                        # 返回说明
        r'# (Step|Phase) \d+: .*',                        # 步骤注释
        r'# End of (function|class|file)',                 # 结束标记注释
        r'# (TODO|FIXME): (implement|fix) this',           # 空泛的 TODO
    ]

    @classmethod
    def strip_slop(cls, content: str) -> str:
        """剔除代码中的语义冗余"""
        lines = content.splitlines()
        cleaned_lines = []

        for line in lines:
            stripped = line.strip()

            # 1. 检查废话注释模式
            if any(re.match(p, stripped, re.IGNORECASE) for p in cls.SLOP_PATTERNS):
                continue

            # 2. 检查自描述性极强的无意义注释 (例如: x = 1 # assign 1 to x)
            # 简单的启发式检查
            if '#' in line:
                parts = line.split('#', 1)
                code_part = parts[0]
                comment_part = parts[1]
                if code_part.strip() and comment_part.strip().lower() in code_part.strip().lower():
                    line = code_part.rstrip()

            cleaned_lines.append(line)

        # 再次处理以移除多余空行
        final_content = "\n".join(cleaned_lines)
        # 合并连续空行 (超过2个)
        final_content = re.sub(r'\n{3,}', '\n\n', final_content)

        # 3. 移除类/函数定义前后的多余空行
        final_content = re.sub(r'(\n\s*(def|class) .*\:)\n\s*\n', r'\1\n', final_content)

        return final_content.strip() + "\n"

    @classmethod
    def analyze_smells(cls, content: str) -> list[str]:
        """识别代码异味 (借鉴 OMX 分类)"""
        smells = []
        if re.search(r'#.*#.*#', content): smells.append("Too many inline comments")
        if re.search(r'(def|class) .*\:\n(\s*#.*\n){5,}', content): smells.append("Comment bloat at start of block")
        if len(re.findall(r'\n\s*\n\s*\n', content)) > 3: smells.append("Excessive vertical whitespace")
        return smells

    @classmethod
    def clean_file(cls, file_path: Path | str):
        path = Path(file_path)
        if not path.exists(): return

        content = path.read_text(encoding='utf-8')
        cleaned = cls.strip_slop(content)

        if len(cleaned) < len(content):
            path.write_text(cleaned, encoding='utf-8')
            return True
        return False
