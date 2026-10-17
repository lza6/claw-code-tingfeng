"""`python -m src` 的统一入口。

## 为什么需要这个文件

本仓库历史上存在**两个互不相通的 CLI**：

| 调用方式 | 实现 | 命令集 |
|:---|:---|:---|
| `clawd`（`pyproject.toml` 的 console script） | `src.cli.entrypoint`（Typer） | chat / run / doctor / agent / workflow / pipeline / … |
| `python -m src.main` | `src.main`（argparse） | chat / doctor / cost-report / evolve / workflow |

同一个 `workflow` 在两个入口下含义不同（一个是 5 阶段引擎，一个是
ralph/ralplan/team/autopilot 命令组）。用户按文档跑 `python -m src.main workflow`
拿到的行为，与 `clawd workflow` 完全不一样 —— 这是真实的调用契约漂移。

现在 `python -m src` 明确指向**唯一的规范入口**（与 `clawd` 完全一致）。
`python -m src.main` 保留为历史 argparse 入口，不再作为推荐用法。
"""

from src.cli.entrypoint import main

if __name__ == "__main__":
    main()
