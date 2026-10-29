"""硬指标的**唯一**数值来源。

## 为什么单独一个文件

2026-10-23 审查指出：同一个阈值散落在 4 处，且有两处不同值——

| 位置 | 值 |
|:---|:---|
| `.github/workflows/ci.yml` | `--min-reachable 443` / `--fail-over 159` |
| `scripts/baseline.py` | `MIN_REACHABLE=443` / `MAX_SILENT_EXCEPT=162` |
| `scripts/check_silent_except.py` | `BASELINE = 172` |
| `.agent/memory/verified-scope.md` | 文档里写 `--min-reachable 442`（旧值） |

阈值只允许在这里定义一次，其余全部 import。CI 不再传数值参数，
脚本用默认值即启用门禁。

改动这些值 = 放宽/收紧质量门槛，必须在 CHANGELOG 里写明理由与实测基线。
"""

from __future__ import annotations

# 生产可达模块数下限（删码/改导入形式后不得下降）
# 443 = 2026-10-23 实测值（442 → 443 是补入 src.__main__ 入口种子的口径修正）
MIN_REACHABLE = 443

# 静默吞异常上限（AST 口径：except 体只含 pass / ...），只允许下降
MAX_SILENT_EXCEPT = 159

# 覆盖率下限（百分比），必须与 pyproject.toml 的 [tool.coverage.report] fail_under 相等
# （tests/scripts/test_baseline_gate.py::test_thresholds_are_single_source_of_truth 会检查）
MIN_COVERAGE_PERCENT = 60
