import pytest
import os
from pathlib import Path
from src.rag.trigram_index import TrigramIndex

def test_incremental_update(tmp_path):
    # Arrange
    root = tmp_path / "src"
    root.mkdir()

    file1 = root / "main.py"
    file1.write_text("print('hello world')", encoding='utf-8')

    index = TrigramIndex()
    index.update_index(root)

    # Assert initial index
    assert str(file1.resolve()) in index.path_to_id
    assert len(index.get_candidates("hello")) > 0

    # Act: Modify file
    import time
    time.sleep(1.1) # Ensure mtime changes
    file1.write_text("print('hello universe')", encoding='utf-8')
    index.update_index(root)

    # Assert updated index
    assert len(index.get_candidates("universe")) > 0

    # Act: Add new file
    file2 = root / "utils.py"
    file2.write_text("def helper(): pass", encoding='utf-8')
    index.update_index(root)

    # Assert new file added
    assert str(file2.resolve()) in index.path_to_id

    # Act: Remove file
    file1.unlink()
    index.update_index(root)

    # Assert file removed
    assert str(file1.resolve()) not in index.path_to_id
    assert len(index.get_candidates("universe")) == 0
