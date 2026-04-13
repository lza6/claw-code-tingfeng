"""IO Adapter - Input/Output handling from Aider

Adapted from aider/io.py (1191 lines)
Provides: Command completion, user input, file I/O with proper escaping
"""

import sys
from pathlib import Path


class InputOutput:
    """Handles all user input/output with proper escaping and completion."""

    def __init__(
        self,
        pretty=True,
        chat_history=None,
        input_history=None,
        use_system_prompt=False,
        system_prompt=None,
        verify_ssl=True,
    ):
        self.pretty = pretty
        self.chat_history = chat_history or []
        self.input_history = input_history or []
        self.use_system_prompt = use_system_prompt
        self.system_prompt = system_prompt
        self.verify_ssl = verify_ssl

        # For testing
        self._last_input = None
        self._last_tool_output = None

    def confirm_ask(self, question: str, default: bool = False) -> bool:
        """Ask a yes/no question."""
        if default:
            prompt = f"{question} (Y/n): "
        else:
            prompt = f"{question} (y/N): "

        response = input(prompt).strip().lower()
        if not response:
            return default
        return response in ("y", "yes")

    def tool_output(self, msg: str, non_json: bool = False):
        """Output a tool result to the user."""
        print(msg)
        self._last_tool_output = msg

    def tool_error(self, msg: str):
        """Output an error message."""
        print(f"ERROR: {msg}", file=sys.stderr)

    def tool_warning(self, msg: str):
        """Output a warning message."""
        print(f"WARNING: {msg}", file=sys.stderr)

    def get_input(self, pre_fill: str = "") -> str:
        """Get input from the user."""
        if pre_fill:
            user_input = input(f"{pre_fill}> ").strip()
        else:
            user_input = input("> ").strip()

        self._last_input = user_input
        return user_input

    def read_text(self, file_path: Path) -> str | None:
        """Read text file content."""
        try:
            return file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self.tool_error(f"Error reading {file_path}: {e}")
            return None

    def write_text(self, file_path: Path, content: str):
        """Write text file content."""
        try:
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return True
        except OSError as e:
            self.tool_error(f"Error writing {file_path}: {e}")
            return False

    def append_text(self, file_path: Path, content: str):
        """Append text to file."""
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(content)
            return True
        except OSError as e:
            self.tool_error(f"Error appending to {file_path}: {e}")
            return False


class CommandCompletionException(Exception):
    """Raised when command completion is needed."""
    pass


def get_completions(
    io: InputOutput,
    cmd: str,
    completions: list[str],
    complete_same_line: bool = False,
) -> list[str] | None:
    """Get command completions based on context."""
    # Simple completion logic - can be extended
    if not completions:
        return None

    # Filter completions based on what user typed
    words = cmd.split()
    if not words:
        return completions

    last_word = words[-1]
    matching = [c for c in completions if c.startswith(last_word)]

    if len(matching) == 1:
        return matching
    elif len(matching) > 1:
        io.tool_output("Possible completions:")
        for m in matching:
            io.tool_output(f"  {m}")
        return None

    return None


def sanitize_json_str(s: str) -> str:
    """Sanitize string for JSON output."""
    # Remove or escape problematic characters
    s = s.replace("\x00", "")
    return s


def prompt_toolkit_available() -> bool:
    """Check if prompt_toolkit is available."""
    try:
        import prompt_toolkit  # noqa: F401
        return True
    except ImportError:
        return False


def get_prompt_settings():
    """Get prompt_toolkit settings if available."""
    if not prompt_toolkit_available():
        return None

    try:
        from prompt_toolkit.formatted import FormattedText
        from prompt_toolkit.shortcuts import PromptSession
        return {"FormattedText": FormattedText, "PromptSession": PromptSession}
    except ImportError:
        return None


__all__ = [
    "CommandCompletionException",
    "InputOutput",
    "get_completions",
    "get_prompt_settings",
    "prompt_toolkit_available",
    "sanitize_json_str",
]
