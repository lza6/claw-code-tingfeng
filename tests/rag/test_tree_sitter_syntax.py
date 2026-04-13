import pytest
from src.rag.tree_sitter_syntax import parse_code, extract_code_blocks, SyntaxTree

def test_extract_code_blocks_python():
    code = """
class MyClass:
    def __init__(self):
        pass

def top_level_func():
    print("hello")
    if True:
        print("nested")
"""
    # 模拟 tree-sitter 不可用时的正则/启发式回退逻辑
    tree = parse_code(code, "python")
    if tree is None:
        # 如果 tree-sitter 没装，parse_code 返回 None，我们手动构造一个满足测试的对象
        # 因为 extract_code_blocks 需要 SyntaxTree 对象
        tree = SyntaxTree(None, code, "python")

    blocks = extract_code_blocks(tree)

    # 验证类
    class_blocks = [b for b in blocks if b["type"] == "class"]
    assert len(class_blocks) == 1
    assert class_blocks[0]["name"] == "MyClass"
    assert "class MyClass:" in class_blocks[0]["content"]
    assert "def __init__(self):" in class_blocks[0]["content"]

    # 验证函数
    func_blocks = [b for b in blocks if b["type"] == "function"]
    # 注意：__init__ 也会被识别为函数（如果正则匹配到）
    # 当前实现中，__init__ 会在类的内容里，但也可能被独立提取
    assert any(b["name"] == "top_level_func" for b in func_blocks)

    top_func = [b for b in func_blocks if b["name"] == "top_level_func"][0]
    assert "print(\"hello\")" in top_func["content"]
    assert "if True:" in top_func["content"]

def test_extract_code_blocks_js_style():
    code = """
function hello(name) {
    console.log("hello " + name);
}

class User {
    constructor(name) {
        this.name = name;
    }
}
"""
    tree = SyntaxTree(None, code, "javascript")
    blocks = extract_code_blocks(tree)

    funcs = [b for b in blocks if b["type"] == "function"]
    assert len(funcs) == 1
    assert funcs[0]["name"] == "hello"
    assert "{" in funcs[0]["content"]
    assert "}" in funcs[0]["content"]

    classes = [b for b in blocks if b["type"] == "class"]
    assert len(classes) == 1
    assert classes[0]["name"] == "User"
    assert "constructor" in classes[0]["content"]

def test_extract_code_blocks_empty():
    tree = SyntaxTree(None, "", "python")
    blocks = extract_code_blocks(tree)
    assert blocks == []
