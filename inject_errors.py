import json
import time
from pathlib import Path
import sys
import os

# Ensure src is in path
sys.path.append(os.getcwd())

from src.core.experience_bank import ExperienceBank

def inject_mock_errors():
    bank = ExperienceBank(storage_path=Path(".clawd/experience.json"))
    # 模拟一个高频错误：ModuleNotFoundError
    for i in range(10):
        bank.record_experience(
            error_pattern="ModuleNotFoundError: No module named 'non_existent_module'",
            error_category="ImportError",
            fix_strategy="Mock strategy",
            success=False,
            error_traceback=f"Traceback {i}: ModuleNotFoundError: No module named 'non_existent_module'"
        )
    print(f"[*] 已注入 10 条模拟错误记录到经验库")

if __name__ == "__main__":
    inject_mock_errors()
