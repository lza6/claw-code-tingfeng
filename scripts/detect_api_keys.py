#!/usr/bin/env python
"""检测硬编码 API 密钥（pre-commit 本地 hook 的实体）。

此前这段脚本被内联在 `.pre-commit-config.yaml` 的 `entry: python -c "..."` 里 ——
多行 Python 嵌在 YAML 双引号标量中根本不是合法 YAML（pre-commit 报
InvalidConfigError: could not find expected ':'，CI 的 Quality Checks 自引入起全红）。
抽成真实脚本后配置恢复可解析，扫描逻辑一字未改。

跳过：`.example` 文件与测试文件（fixture 里的假密钥不是泄露）。
"""
from __future__ import annotations

import re
import sys

# 常见 API 密钥模式
PATTERNS = [
    (r'sk-or-v1-[A-Za-z0-9]{32,}', 'OpenRouter API Key'),
    (r'sk-[A-Za-z0-9]{32,}', 'OpenAI API Key'),
    (r'sk-ant-[A-Za-z0-9]{32,}', 'Anthropic API Key'),
    (r'AIza[A-Za-z0-9_-]{32,}', 'Google API Key'),
    (r'gsk_[A-Za-z0-9]{32,}', 'Groq API Key'),
    (r'ghp_[A-Za-z0-9]{36,}', 'GitHub Personal Access Token'),
    (r'AKIA[A-Za-z0-9]{16}', 'AWS Access Key'),
]


def main(argv: list[str]) -> int:
    found = False
    for filename in argv:
        # 跳过 .env.example 和测试文件
        if filename.endswith('.example') or 'test_' in filename:
            continue
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            for pattern, name in PATTERNS:
                if re.search(pattern, content):
                    print(f'检测到可能的 {name} 在文件: {filename}')
                    found = True
        except Exception:
            pass

    if found:
        print('\n检测到硬编码的 API 密钥！请使用环境变量或 .env 文件。')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
