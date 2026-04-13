import pytest
from src.tools_runtime.bash_security import is_shell_command_read_only

@pytest.mark.parametrize("command, expected", [
    ("ls", True),
    ("ls -la", True),
    ("cat file.txt", True),
    ("grep 'pattern' file.txt", True),
    ("git status", True),
    ("git diff", True),
    ("git log", True),
    ("find . -name '*.py'", True),
    ("echo 'hello'", True),
    ("pwd", True),
    ("whoami", True),
    ("df -h", True),
    ("du -sh .", True),
    # Dangerous/Write operations
    ("rm -rf /", False),
    ("touch new_file.txt", False),
    ("mkdir new_dir", False),
    ("mv file1 file2", False),
    ("cp file1 file2", False),
    ("git commit -m 'msg'", False),
    ("git push", False),
    ("git checkout branch", False),
    ("git branch -D branch", False),
    # Redirections
    ("ls > output.txt", False),
    ("cat file.txt >> log.txt", False),
    ("echo 'test' > /tmp/test", False),
    # Command substitution
    ("echo $(whoami)", False),
    ("ls `pwd` ", False),
    # Pipes with write
    ("ls | xargs rm", False),
    ("cat file.txt | tee output.txt", False), # tee is not in READ_ONLY_ROOT_COMMANDS
    # Environment variables
    ("VAR=val ls", True),
    ("VAR=val touch file", False),
    # Complex chains
    ("ls && pwd", True),
    ("ls && touch file", False),
    ("ls ; pwd", True),
    ("ls ; rm file", False),
    # Shell wrappers
    ("bash -c 'ls'", True),
    ("sh -c 'rm -rf /'", False),
    # Special commands
    ("find . -delete", False),
    ("sed -i 's/a/b/g' file", False),
    ("awk '{system(\"rm file\")}'", False),
])
def test_is_shell_command_read_only(command, expected):
    assert is_shell_command_read_only(command) == expected
