import sys
from pathlib import Path
from src.tools_runtime.bash_tool import BashTool

def test_bash_tool_bypass():
    # Normal mode
    tool_normal = BashTool(workdir=Path.cwd(), bypass_security=False)
    cmd_dangerous = "rm -rf /" if sys.platform != "win32" else "rd /s /q C:\\"
    success, message = tool_normal.validate(command=cmd_dangerous)
    print(f"Normal Mode - Dangerous Command '{cmd_dangerous}': Success={success}, Message='{message}'")

    # Bypass mode
    tool_bypass = BashTool(workdir=Path.cwd(), bypass_security=True)
    success, message = tool_bypass.validate(command=cmd_dangerous)
    print(f"Bypass Mode - Dangerous Command '{cmd_dangerous}': Success={success}, Message='{message}'")

if __name__ == "__main__":
    test_bash_tool_bypass()
