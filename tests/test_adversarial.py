import unittest
import os
import json
from pathlib import Path
from src.tools_runtime.file_read_tool import FileReadTool
from src.tools_runtime.bundle_tool import BundleTool
from src.tools_runtime.recency_tools import HotFilesTool, DependencyTool
from src.utils.recency import RecencyTracker
from src.tools_runtime.registry import ToolRegistry

class TestAdversarial(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tmp_adversarial_test")
        self.test_dir.mkdir(exist_ok=True)
        self.registry = ToolRegistry()
        
    def tearDown(self):
        # Cleanup
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_large_file_read(self):
        """Test reading a very large file to ensure no OOM or crash."""
        large_file = self.test_dir / "large.txt"
        content = "A" * (1024 * 1024) # 1MB (MAX_FILE_SIZE is 5MB)
        large_file.write_text(content)
        
        tool = FileReadTool(base_path=self.test_dir)
        result = tool.execute(file_path="large.txt", limit=100)
        self.assertTrue(result.success)
        self.assertIn("FileReadTool", tool.name)

    def test_invalid_utf8_binary(self):
        """Test handling of binary files (invalid UTF-8)."""
        bin_file = self.test_dir / "binary.bin"
        with open(bin_file, "wb") as f:
            f.write(b"\xff\xfe\xfd\x00\x01\x02")
            
        tool = FileReadTool(base_path=self.test_dir)
        result = tool.execute(file_path="binary.bin")
        # Validate should catch binary extension (.bin is in common binary list)
        if not result.success:
            # Check for extension in error msg instead of specific Chinese/English text
            self.assertIn(".bin", result.error.lower())
        else:
            self.assertIn("\ufffd", result.output)

    def test_bundle_tool_recursion_safety(self):
        """Test that BundleTool handles recursion safely."""
        bundle = BundleTool(registry=self.registry)
        # Register bundle as a tool
        self.registry.register(bundle)
        
        # Self-referential bundle
        ops = [
            {"tool": "bundle", "arguments": {"ops": [{"tool": "bundle", "arguments": {"ops": []}}]}}
        ]
        # In the current implementation, this will just call bundle again.
        # It won't infinite loop because the nested bundle call will finish.
        result = bundle.execute(ops=ops)
        self.assertTrue(result.success)

    def test_recency_tracker_edge_cases(self):
        """Test RecencyTracker with empty dirs and rapid changes."""
        tracker = RecencyTracker(root_dir=self.test_dir)
        tracker.scan()
        self.assertEqual(len(tracker.get_hot_files()), 0)
        
        # Add a file
        f1 = self.test_dir / "f1.py"
        f1.write_text("print(1)")
        tracker.scan()
        hot = tracker.get_hot_files()
        self.assertEqual(len(hot), 1)
        # RecencyTracker.get_hot_files returns List[str] (rel_paths)
        self.assertEqual(hot[0], "f1.py")

    def test_dependency_tool_missing_file(self):
        """Test DependencyTool with non-existent target."""
        tool = DependencyTool(root_dir=self.test_dir)
        result = tool.execute(path="non_existent.py")
        self.assertTrue(result.success) # Should return empty list, not error
        data = json.loads(result.output)
        self.assertEqual(len(data.get("imported_by", [])), 0)

if __name__ == "__main__":
    unittest.main()
