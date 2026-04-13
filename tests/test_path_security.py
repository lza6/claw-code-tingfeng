"""Unit tests for src/utils/path_security.py."""
import pytest
from pathlib import Path
from src.utils.path_security import validate_path, is_sensitive_file

def test_sensitive_file_detection():
    assert is_sensitive_file(".env") is True
    assert is_sensitive_file("id_rsa") is True
    assert is_sensitive_file("main.py") is False
    assert is_sensitive_file("config.json") is False

def test_path_validation_traversal():
    base = Path("c:/Users/Administrator.DESKTOP-EGNE9ND/Desktop/claw-code-tingfeng").resolve()
    
    # Valid path
    valid = validate_path("src/main.py", base)
    assert valid.name == "main.py"
    
    # Outside boundary (traversal)
    with pytest.raises(PermissionError, match="Adversarial path detected"):
        validate_path("../../../etc/passwd", base)

def test_path_validation_sensitive():
    base = Path("c:/Users/Administrator.DESKTOP-EGNE9ND/Desktop/claw-code-tingfeng").resolve()
    
    # Access blocked sensitive file
    with pytest.raises(PermissionError, match="Access denied to sensitive file"):
        validate_path(".env", base)

def test_forbidden_directories():
    base = Path("c:/Users/Administrator.DESKTOP-EGNE9ND/Desktop/claw-code-tingfeng").resolve()
    
    with pytest.raises(PermissionError, match="Access denied to forbidden directory"):
        validate_path(".git/config", base)
