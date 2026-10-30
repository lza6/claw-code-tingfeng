"""任务状态枚举（原 `src/workflow/models.py:WorkflowStatus`）

下沉原因：`core/persistence/run_state.py` 运行时真的用 `WorkflowStatus.RUNNING`
（update_task / mark_file_touched），而 core 不允许 import 上层 workflow
（见 scripts/core_surface.py）。这个枚举没有依赖，搬到 core 顶层最干净；
`workflow/models.py` 保留 re-export，旧 import 不用改。

注意：不要放到 `core/models/` —— 那里已经有一个 `core/models.py` 模块，
建同名目录会把模块遮蔽掉（本轮真实踩到：`from .models import PermissionDenial` 直接 ImportError）。
"""

from __future__ import annotations

from enum import Enum


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
