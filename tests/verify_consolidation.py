import sys
import os
import asyncio
import unittest
from pathlib import Path

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.utils.retry import retry_with_backoff
from src.utils.file_ops import atomic_write
from src.utils.cache import LruCache
from src.core.settings import get_settings, ApprovalMode
from src.core.output_compressor import OutputCompressor

class TestConsolidation(unittest.TestCase):
    def test_cache(self):
        cache = LruCache(capacity=2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)
        cache.put("c", 3)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("c"), 3)

    def test_atomic_write(self):
        test_file = Path("tmp_test_atomic.txt")
        content = "hello world"
        atomic_write(test_file, content)
        self.assertTrue(test_file.exists())
        self.assertEqual(test_file.read_text(), content)
        test_file.unlink()

    def test_settings_approval_mode(self):
        settings = get_settings()
        self.assertTrue(hasattr(settings, "approval_mode"))
        self.assertIn(settings.approval_mode, [m for m in ApprovalMode])

    def test_output_compressor_save_to_file(self):
        compressor = OutputCompressor()
        # Create a very large output (>25000)
        large_output = "Line content\n" * 3000 
        command = "cat huge_file.txt"
        
        # This should trigger truncation and save to file
        compressed = compressor.compress(command, large_output)
        
        self.assertIn("⚠️  Output was significantly truncated", compressed)
        self.assertIn("Full output saved to:", compressed)
        
        # Extract path
        import re
        match = re.search(r"Full output saved to: (.*)\n", compressed)
        if match:
            path = Path(match.group(1).strip())
            self.assertTrue(path.exists())
            # Cleanup
            path.unlink()

async def run_retry_test():
    count = 0
    async def failing_func():
        nonlocal count
        count += 1
        if count < 3:
            raise Exception("Transient error")
        return "success"
    
    result = await retry_with_backoff(
        failing_func, 
        max_attempts=5, 
        initial_delay_ms=10,
        should_retry=lambda e: "Transient error" in str(e)
    )
    assert result == "success"
    assert count == 3
    print("Retry test passed!")

if __name__ == "__main__":
    # Run sync tests
    unittest.main(exit=False)
    
    # Run async retry test
    asyncio.run(run_retry_test())
