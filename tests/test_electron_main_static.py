"""Electron 主进程/预加载脚本的静态自检（不启动 Electron）

真实事故（v0.86.0 首个安装包）：`main.js` 里 `registerIpcHandlers()` 用了 `ipcMain.handle(...)`，
而同一函数**后面**才 `const { ipcMain, app } = require('electron')` →
`Cannot access 'ipcMain' before initialization`（TDZ）→ 主进程在创建窗口前挂掉，
安装版完全打不开（窗口没出来、Host 不启动）。

这类错误 `node --check` 查不出来（语法合法），只能靠静态核对 + 实装 E2E。
"""

from __future__ import annotations

import re
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1] / "desktop"
MAIN = DESKTOP / "electron" / "main.js"
PRELOAD = DESKTOP / "electron" / "preload.js"

REQUIRE_ELECTRON = "require('electron')"


def _module_level_imports(source: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(r"(?:const|let|var)\s*\{([^}]*)\}\s*=\s*" + re.escape(REQUIRE_ELECTRON), source):
        for part in match.group(1).split(","):
            name = part.split(":")[0].strip()
            if name:
                names.add(name)
    return names


class TestElectronMainStatic:
    def test_ipc_main_is_imported_when_used(self):
        source = MAIN.read_text(encoding="utf-8")
        assert "ipcMain.handle(" in source, "添加项目需要 ipcMain.handle（文件夹选择器）"
        assert "ipcMain" in _module_level_imports(source), (
            "main.js 用了 ipcMain 但没在顶部从 electron 解构导入"
        )

    def test_required_electron_symbols_all_imported(self):
        source = MAIN.read_text(encoding="utf-8")
        imported = _module_level_imports(source)
        used = set(
            re.findall(
                r"\b(app|BrowserWindow|Tray|Menu|nativeImage|ipcMain)\.",
                source,
            )
        )
        missing = used - imported
        assert not missing, f"main.js 用到但未在顶部导入的 electron 符号: {sorted(missing)}"

    def test_no_use_before_inner_destructure(self):
        """函数内"先用后声明"同一符号 = TDZ 崩溃（本次真实事故）

        判据必须按**真实块作用域**圈定：`if (...) { const { dialog } = ... }` 与
        `catch { const { dialog } = ... }` 是两个不同块，合法；按"函数内 20 行"或
        "同缩进"都会误报。这里用「块头行 → 配对 `}`」划定范围。
        """
        lines = MAIN.read_text(encoding="utf-8").splitlines()

        def _indent(row: str) -> int:
            return len(row) - len(row.lstrip())

        def _block_range(idx: int) -> tuple[int, int]:
            indent = _indent(lines[idx])
            head = 0
            for i in range(idx - 1, -1, -1):
                row = lines[i]
                if not row.strip():
                    continue
                if _indent(row) < indent and row.rstrip().endswith(("{", "=> {")):
                    head = i
                    break
            head_indent = _indent(lines[head])
            end = len(lines)
            for j in range(idx + 1, len(lines)):
                row = lines[j]
                if row.strip().startswith("}") and _indent(row) == head_indent:
                    end = j
                    break
            return head, end

        problems: list[str] = []
        for index, line in enumerate(lines):
            if REQUIRE_ELECTRON not in line or not line.startswith("  "):
                continue
            if line.strip().startswith("//"):
                continue  # 注释里提到这行不算真代码
            start = line.find("{")
            end_brace = line.find("}", start + 1)
            if start == -1 or end_brace == -1:
                continue
            names = [part.split(":")[0].strip() for part in line[start + 1:end_brace].split(",")]
            block_start, _block_end = _block_range(index)
            scope_rows = [
                row for row in lines[block_start:index]
                if row.strip() and not row.strip().startswith("//")
            ]
            for name in names:
                if not name:
                    continue
                marker = name + "."
                if any(marker in row for row in scope_rows):
                    problems.append(
                        f"第 {index + 1} 行解构 {name}，但同一块（第 {block_start + 1} 行起）前面已用过 {marker}"
                    )
        assert not problems, "疑似 TDZ（先用后声明，会导致启动即崩）: " + "; ".join(problems)

    def test_no_legacy_application_menu(self):
        source = MAIN.read_text(encoding="utf-8")
        assert "Menu.setApplicationMenu(null)" in source, "应移除 Electron 默认菜单栏（用户明确要求）"

    def test_crash_handlers_write_to_log(self):
        """主进程崩溃必须留痕：Node 15+ 把 unhandledRejection 当致命错误

        真实事故：重启应用后进程 exit 1，shell.log 一行都没有，只能靠猜。
        """
        source = MAIN.read_text(encoding="utf-8")
        assert "process.on('uncaughtException'" in source
        assert "process.on('unhandledRejection'" in source
        assert "[crash]" in source
        # 启动流程整体也要兜住，出错弹框而不是静默退出
        assert "catch (err)" in source
        assert "启动流程失败" in source


class TestElectronPreloadStatic:
    def test_context_bridge_used(self):
        source = PRELOAD.read_text(encoding="utf-8")
        assert "contextBridge.exposeInMainWorld" in source

    def test_no_node_leak_to_renderer(self):
        source = PRELOAD.read_text(encoding="utf-8")
        assert "require('fs')" not in source and 'require("fs")' not in source, (
            "preload 不应把 fs 等 Node 能力透给渲染进程"
        )

    def test_pick_folder_exposed(self):
        source = PRELOAD.read_text(encoding="utf-8")
        assert "pickFolder" in source, "添加项目需要原生文件夹选择器"
