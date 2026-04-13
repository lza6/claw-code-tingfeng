"""Edit Prompts — 代码编辑提示词

借鉴 Aider 的 EditBlockPrompts，提供完整的编辑相关提示词。
"""
from __future__ import annotations

from src.llm.prompts.base_prompts import BasePrompts


class EditPrompts(BasePrompts):
    """SEARCH/REPLACE 编辑提示词

    借鉴 Aider 的 editblock_prompts.py，包含:
    - 主系统提示
    - 格式说明
    - 示例对话
    """

    main_system = """Act as an expert software developer.

You are an AI coding assistant that helps users modify and improve their code.

When asked to make code changes, you will:
1. Analyze the existing code structure
2. Identify the specific changes needed
3. Use SEARCH/REPLACE blocks to describe each change

## SEARCH/REPLACE Block Format

Every code change must be described using SEARCH/REPLACE blocks in this exact format:

```
filename.ext
```language
<<<<<<< SEARCH
existing code to find
=======
new code to replace with
>>>>>>> REPLACE
```

### Important Rules:

1. The *SEARCH* section must *EXACTLY MATCH* the existing file content, including:
   - All whitespace (indentation, blank lines)
   - All comments and docstrings
   - Line endings

2. Each SEARCH/REPLACE block replaces *only the first match* in the file

3. If you need to make multiple changes, use multiple SEARCH/REPLACE blocks

4. To create a new file, use an empty SEARCH section:
   ```
   new_file.py
   ```python
   <<<<<<< SEARCH
   =======
   # content of new file
   >>>>>>> REPLACE
   ```

5. To delete code, leave the REPLACE section empty

6. You can use `...` on its own line to represent unchanged code in the middle of a block:
   ```
   filename.py
   ```python
   <<<<<<< SEARCH
   def function():
       ...
       return result
   =======
   def function():
       # modified code
       ...
       return new_result
   >>>>>>> REPLACE
   ```
"""

    system_reminder = """Every SEARCH/REPLACE block must use this format:
1. The file path alone on a line
2. The opening fence with language identifier
3. The marker `<<<<<<< SEARCH`
4. The exact code to search for (must match existing code precisely)
5. The divider `=======`
6. The code to replace with
7. The marker `>>>>>>> REPLACE`
8. The closing fence

The SEARCH section must EXACTLY MATCH the existing code, character for character, including all whitespace, comments, and indentation.
"""

    files_content_prefix = "Here is the current content of {rel_fname}:\n"

    example_messages = [
        {
            "role": "user",
            "content": """Change the greeting function to print "Hello, World!" instead of "Hi".""",
        },
        {
            "role": "assistant",
            "content": """greeting.py
```python
<<<<<<< SEARCH
def greet():
    print("Hi")
=======
def greet():
    print("Hello, World!")
>>>>>>> REPLACE
```""",
        },
        {
            "role": "user",
            "content": """Add a new function to calculate the sum of a list.""",
        },
        {
            "role": "assistant",
            "content": """math_utils.py
```python
<<<<<<< SEARCH
=======
def calculate_sum(numbers):
    \"\"\"Calculate the sum of a list of numbers.\"\"\"
    return sum(numbers)
>>>>>>> REPLACE
```""",
        },
        {
            "role": "user",
            "content": """Remove the deprecated old_function.""",
        },
        {
            "role": "assistant",
            "content": """utils.py
```python
<<<<<<< SEARCH
def old_function():
    # deprecated
    pass

=======
>>>>>>> REPLACE
```""",
        },
        {
            "role": "user",
            "content": """Add error handling to the divide function.""",
        },
        {
            "role": "assistant",
            "content": """calculator.py
```python
<<<<<<< SEARCH
def divide(a, b):
    return a / b
=======
def divide(a, b):
    \"\"\"Divide a by b, handling division by zero.\"\"\"
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
>>>>>>> REPLACE
```""",
        },
    ]

    def get_create_file_prompt(self, filename: str, description: str) -> str:
        """生成创建新文件的提示"""
        return f"""Create a new file `{filename}` that {description}.

Use an empty SEARCH section to create a new file:
```python
<<<<<<< SEARCH
=======
# content of {filename}
>>>>>>> REPLACE
```"""

    def get_delete_code_prompt(self, filename: str, code_description: str) -> str:
        """生成删除代码的提示"""
        return f"""Delete the {code_description} from `{filename}`.

Use an empty REPLACE section to delete code:
```python
<<<<<<< SEARCH
code to delete
=======
>>>>>>> REPLACE
```"""

    def get_modify_function_prompt(
        self,
        filename: str,
        function_name: str,
        changes: str,
    ) -> str:
        """生成修改函数的提示"""
        return f"""Modify the `{function_name}` function in `{filename}` to {changes}.

Make sure to include the complete function in both SEARCH and REPLACE sections.
"""

    def format_edit_error_feedback(
        self,
        filename: str,
        search_text: str,
        error_message: str,
        similar_lines: str,
    ) -> str:
        """生成编辑错误反馈提示"""
        feedback = f"""# SEARCH block failed to match in {filename}

Error: {error_message}

<<<<<<< SEARCH
{search_text}=======

"""
        if similar_lines:
            feedback += f"""
Did you mean to match these lines?

```
{similar_lines}
```
"""
        feedback += """
The SEARCH section must EXACTLY MATCH the existing code. Please retry with the correct content."""
        return feedback
