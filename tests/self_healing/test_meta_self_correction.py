"""Meta-Self-Correction 专项测试 — 验证高级 AST 审计能力"""
import pytest
import asyncio
from src.self_healing.meta_self_correction import MetaSelfCorrection

@pytest.mark.asyncio
async def test_meta_audit_ast_engine():
    """测试 AST 审计引擎对典型代码异味的识别能力"""
    msc = MetaSelfCorrection()

    bad_code = """
import time

def deep_nested_func():
    if True:
        for i in range(10):
            with open('f.txt', 'w') as f:
                try:
                    if i > 5:
                        print("too deep")
                except:
                    pass

async def async_with_sleep():
    time.sleep(1)
    """

    result = await msc.self_audit("test_bad_module.py", bad_code)

    # 1. 验证裸 except 探测
    assert any("裸 except:" in f for f in result.findings)

    # 2. 验证深度嵌套探测
    assert any("嵌套过深" in f for f in result.findings)

    # 3. 验证异步 sleep 探测
    assert any("time.sleep" in f for f in result.findings)

    # 4. 验证严重等级自动提升
    assert result.severity == "medium"
    assert len(result.recommendations) >= 3

@pytest.mark.asyncio
async def test_meta_audit_clean_code():
    """测试干净代码不应产生冗余 findings"""
    msc = MetaSelfCorrection()

    clean_code = """
def simple_func(x):
    return x + 1
    """

    result = await msc.self_audit("clean.py", clean_code)
    assert len(result.findings) == 0
    assert result.severity == "low"
