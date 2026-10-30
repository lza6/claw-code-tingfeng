"""CLI 输出契约 —— `--json` 全覆盖的基础设施（高阶提案 X-7）

## 为什么需要

`clawd` 有二十多个命令组，但只有 `reason` 支持 `--json`，其余全是"人读文本"：
脚本、CI、外部工具都没法消费输出，只能 grep 屏幕文字。这是"CLI 能用但不好自动化"的根因。

## 契约

每个命令产出一个 `CommandResult`：

- `ok`：业务是否成功（与退出码一致，避免"exit 0 但其实失败"）
- `data`：**机器可读**的结构（字段名是契约，有测试锁住）
- `human`：人读正文（默认输出，保持现有体验不变）
- `exit_code`：进程退出码（默认由 `ok` 推导）

`emit()` 按 `--json` 开关二选一输出，**退出码两者一致** —— 这样 `--json` 只是换了输出形态，
不改变行为语义。

## 用法

```python
@app.command()
def session_list(json_output: bool = typer.Option(False, "--json", help="机器可读输出")):
    views = list_sessions()
    result = CommandResult(
        ok=True,
        data={"sessions": [...], "count": len(views)},
        human="算了 N 个会话",
    )
    raise typer.Exit(emit(result, json_output))
```
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    """命令结果（人读 + 机读的统一形态）"""

    ok: bool = True
    #: 机器可读数据（`--json` 时原样输出）；字段名即契约
    data: dict[str, Any] = field(default_factory=dict)
    #: 人读正文（默认输出；`--json` 时丢弃）
    human: str = ""
    #: 覆写退出码（默认 ok → 0 / not ok → 1）
    exit_code: int | None = None

    @property
    def code(self) -> int:
        if self.exit_code is not None:
            return int(self.exit_code)
        return 0 if self.ok else 1

    def to_payload(self) -> dict[str, Any]:
        """`--json` 输出的顶层结构（固定字段，便于脚本稳定解析）"""
        return {"ok": bool(self.ok), "code": self.code, **dict(self.data)}

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, default=str)

    def render(self) -> str:
        """人读正文；为空时退回 JSON（避免"什么都没输出"的困惑）"""
        return self.human if self.human.strip() else self.to_json()


def emit(result: CommandResult, as_json: bool = False, *, stream=None) -> int:
    """按 `--json` 输出并返回退出码（调用方 `raise typer.Exit(emit(...))`）

    - `as_json=False`：打印人读正文（保持现有 CLI 体验）
    - `as_json=True`：打印单行 JSON（stdout，便于 `| jq`）
    - **错误信息不会混进 stdout 的 JSON**：`--json` 下失败也输出合法 JSON（`ok=false`），
      而不是把中文错误和 JSON 拼在一起（那样脚本解析必崩）
    """
    out = sys.stdout if stream is None else stream
    text = result.to_json() if as_json else result.render()
    print(text, file=out)
    return result.code
