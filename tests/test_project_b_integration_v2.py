import sys
from pathlib import Path
from src.rag.symbol_extractor import SymbolExtractor
from src.rag.scope_detector import ScopeDetector
from src.tools_runtime.grep_tool import GrepTool

def test_symbol_extractor():
    print("Testing SymbolExtractor...")
    extractor = SymbolExtractor()
    
    # Test Python
    py_code = """
class MyClass:
    def method_a(self):
        pass
        
def top_level_func():
    pass
"""
    outline = extractor.extract("test.py", py_code)
    print(f"Python symbols: {[s.name for s in outline.symbols]}")
    assert "MyClass" in [s.name for s in outline.symbols]
    assert "method_a" in [s.name for s in outline.symbols]
    assert "top_level_func" in [s.name for s in outline.symbols]
    
    # Test Rust (New language)
    rs_code = """
pub struct Point { x: i32, y: i32 }
fn main() {
    println!("Hello");
}
use std::collections::HashMap;
"""
    outline = extractor.extract("main.rs", rs_code)
    print(f"Rust symbols: {[s.name for s in outline.symbols]}")
    assert "Point" in [s.name for s in outline.symbols]
    assert "main" in [s.name for s in outline.symbols]
    
    print("SymbolExtractor tests passed!")

def test_grep_scope():
    print("\nTesting GrepTool with scope...")
    # Create a temporary file for testing
    test_file = Path("temp_test_file.py")
    test_file.write_text("""
class Calculator:
    def add(self, a, b):
        return a + b  # TARGET_LINE
        
    def subtract(self, a, b):
        return a - b
""")
    
    try:
        tool = GrepTool(base_path=Path.cwd())
        result = tool.execute(pattern="TARGET_LINE", scope=True, file_pattern="temp_test_file.py")
        print(f"Grep result:\n{result.output}")
        assert "[in function add]" in result.output
    finally:
        if test_file.exists():
            test_file.unlink()
            
    print("GrepTool scope test passed!")

if __name__ == "__main__":
    try:
        test_symbol_extractor()
        test_grep_scope()
        print("\nAll integration tests passed successfully!")
    except Exception as e:
        print(f"\nTests failed: {e}")
        sys.exit(1)
