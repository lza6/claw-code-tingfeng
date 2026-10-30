"""准备桌面端打包的 host/ — 白名单复制（只带真实依赖）

用法: venv/Scripts/python.exe scripts/prepare_host_bundle.py
依赖解析: AST 扫 src 的 import → venv site-packages 直接匹配 → 白名单
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 打包日志里有中文与路径，Windows 控制台默认 GBK 会在 print 时抛 UnicodeEncodeError
# （把"打包失败的原因"变成"脚本崩了"，真实踩过）。强制 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).parent.parent
OUT = ROOT / "desktop" / "host"
VENV = ROOT / "venv"
SP = VENV / "Lib" / "site-packages"

# AST 扫描出的直接依赖 + 人工补的传递依赖（实测 litellm/openai/pydantic 链）
#
# 还有一类必须显式列：**requirements.txt 里声明了、但代码是延迟 import 的包**
# （AST 扫描看不见）。漏了它们，桌面端会出现"命令存在但一用就缺包"：
#   celery/redis → 后台任务；git/gitdb/smmap（GitPython）→ `clawd git`（undo/diff/commit）；
#   opentelemetry → tracing；rope/jedi/parso/pyflakes/pylsp/pluggy → LSP 相关。
# 实测这些加起来只有 ~27MB，相对 300MB 的 bundle 不值一提，所以直接全带。
WHITELIST_EXTRA = {
    # 后台任务（requirements: celery[redis] / redis）
    "celery", "redis", "kombu", "billiard", "amqp", "vine",
    "click_didyoumean", "click_plugins", "click_repl",
    # Git 操作（requirements: GitPython）——`clawd git undo/diff/commit` 依赖
    "git", "gitdb", "smmap",
    # 可观测性（requirements: opentelemetry-*）
    "opentelemetry",
    # LSP / 静态检查（requirements: python-lsp-server / jedi / pyflakes）
    "pylsp", "jedi", "parso", "pyflakes", "rope", "pluggy",
    "pydantic_core", "annotated_types", "typing_inspection", "anyio", "sniffio",
    "idna", "certifi", "httpcore", "h11", "jiter", "distro", "tqdm", "regex",
    "charset_normalizer", "urllib3", "six", "dateutil", "python_dateutil",
    "soupsieve", "aiohappyeyeballs", "multidict", "yarl", "frozenlist", "attrs",
    "propcache", "importlib_metadata", "zipp", "markupsafe", "itsdangerous",
    "click", "starlette", "jinja2", "cffi", "pycparser", "pycryptodome",
    "Crypto", "tokenizers", "tiktoken_ext", "reference", "rpds", "referencing",
    "jsonschema_specifications", "openapi", "pydantic_settings", "dotenv",
    "grep_ast", "tree_sitter_languages_pack", "plumbum", "ptyprocess",
    "bin", "litellm",
    # typer→rich 渲染链（clawd CLI 用 typer，import 时即需）
    "markdown_it", "mdurl", "pygments", "pygments_lexers", "shellingham",
    "textual",
    # loguru 的 Windows 可选加速模块：不在 loguru 的 pip Requires 里（只有 extra），
    # 缺了会让打包版每次启动打一条"模块导入失败"噪音
    "win32_setctime",
}


def _chunks(items: list[str], size: int) -> list[list[str]]:
    """按固定大小切批（pip show 命令行长度保护）"""
    return [items[i:i + size] for i in range(0, len(items), size)]


def resolve_transitive(seed_names: set[str]) -> set[str]:
    """用 pip show 递归解析传递依赖（Requires 字段），直到闭包稳定。

    dist-info 的拓扑比 import 名可靠（处理了横杠/下划线归一）。
    """
    closed = set(seed_names)
    frontier = set(seed_names)
    while frontier:
        # 注意：pip show 只接受**空格分隔的多个参数**，传 "a,b,c" 会被当成一个包名
        # （WARNING: Package(s) not found）→ 闭包永远为空、白名单只剩直接依赖。
        # 这正是之前要手工往 WHITELIST_EXTRA 里补 pydantic_core/anyio/certifi 的原因，
        # 也是打包版 `ModuleNotFoundError: annotated_doc`（typer 的间接依赖）的根因。
        # 分批避免命令行过长。
        batch: list[str] = []
        nxt: set[str] = set()
        for chunk in _chunks(sorted(frontier), 40):
            r = subprocess.run(
                [str(VENV / "Scripts" / "python.exe"), "-m", "pip", "show", *chunk],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            batch.append(r.stdout or "")
        stdout_all = "\n".join(batch)
        cur: str | None = None
        for line in stdout_all.splitlines():
            if line.startswith("Name:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("Requires:") and cur:
                reqs = line.split(":", 1)[1].strip()
                if reqs:
                    for req in reqs.split(","):
                        req = req.strip().split(";")[0].split(" ")[0].strip()
                        # 去掉版本约束
                        req = req.split(">")[0].split("<")[0].split("=")[0].split("!")[0].strip()
                        if req and req not in closed:
                            # 归一到 site-packages 实际目录名
                            for cand in (req, req.replace("-", "_")):
                                if (SP / cand).exists() or (SP / f"{cand}.py").exists():
                                    name = (SP / cand).name if (SP / cand).exists() else (SP / f"{cand}.py").name
                                    if name not in closed:
                                        nxt.add(name)
                                    break
        closed |= nxt
        frontier = nxt
    return closed


def collect_whitelist() -> set[str]:
    """AST 扫 src 的顶层第三方 import，映射到 site-packages 实际目录名"""
    tops: set[str] = set()
    for f in (ROOT / "src").rglob("*.py"):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    tops.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                tops.add(node.module.split(".")[0])
    std = set(sys.stdlib_module_names)
    third = {t for t in tops if t not in std and not t.startswith("_") and t != "src"}

    names: set[str] = set(WHITELIST_EXTRA)
    for t in third:
        for cand in (t, t.replace("_", "-")):
            if (SP / cand).exists() or (SP / f"{cand}.py").exists():
                # 统一成实际条目名（目录或单文件 .py）
                entry = cand if (SP / cand).exists() else f"{cand}.py"
                names.add((SP / entry).name)
                break
    # pip 递归解析传递依赖闭包
    names = resolve_transitive(names)
    return names


def robocopy(src: Path, dst: Path, exclude_dirs: list[str] | None = None) -> int:
    cmd = ["robocopy", str(src), str(dst), "/E", "/MT:16", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]
    if exclude_dirs:
        # robocopy /XD 必须在文件参数位置之后；用通配 * 表示全文件
        cmd.insert(2, "*")
        for d in exclude_dirs:
            cmd += ["/XD", d]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode >= 8:
        print(r.stderr.decode(errors="replace")[:500])
        raise SystemExit(f"robocopy 失败 ({r.returncode}): {src} → {dst}")
    return r.returncode


def rmtree_with_retry(path: Path, attempts: int = 6, delay: float = 3.0) -> None:
    """删除目录（Windows 上会被杀软/索引器短暂占用 → WinError 32）

    实测：直接 `shutil.rmtree` 每次锁在**不同**的 site-packages 文件上，
    重试即可通过；不重试则整个打包流程直接失败（2026-10-29 真实踩到）。
    """
    import time

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError as e:  # WinError 32：文件被占用
            last = e
            print(f"  文件被占用，{delay:.0f}s 后重试删除（{attempt}/{attempts}）")
            time.sleep(delay)
    raise SystemExit(f"清理旧 bundle 失败（{attempts} 次重试仍被占用）: {last}")


def main() -> int:
    if OUT.exists():
        print(f"清理旧 bundle: {OUT}")
        rmtree_with_retry(OUT)

    sys_base = Path(sys.base_prefix)
    py_out = OUT / "python"
    py_out.mkdir(parents=True, exist_ok=True)

    print("[1/4] Python 运行时（系统解释器 + stdlib）")
    for item in ["python.exe", "pythonw.exe"]:
        src = sys_base / item
        if src.exists():
            (py_out / item).write_bytes(src.read_bytes())
    # 顶层 **所有** *.dll 一起带。此前手写清单漏了 `python3.dll`（稳定 ABI 转发），
    # 结果 C 扩展加载失败：`ImportError: DLL load failed while importing _psutil_windows`
    # —— 这类"少一个 DLL"的错误只有真 import 才会现形。
    for dll in sys_base.glob("*.dll"):
        (py_out / dll.name).write_bytes(dll.read_bytes())
    for archive in sys_base.glob("python3*.zip"):
        (py_out / archive.name).write_bytes(archive.read_bytes())
    robocopy(sys_base / "DLLs", py_out / "DLLs")
    robocopy(sys_base / "Lib", py_out / "Lib",
             exclude_dirs=["__pycache__", "idlelib", "tkinter", "turtledemo", "test", "site-packages"])

    print("[2/4] site-packages 白名单复制")
    whitelist = collect_whitelist()
    print(f"  白名单 {len(whitelist)} 个包")
    sp_out = py_out / "Lib" / "site-packages"
    sp_out.mkdir(parents=True, exist_ok=True)
    copied_di: set[str] = set()
    for name in sorted(whitelist):
        src = SP / name
        if src.is_dir():
            robocopy(src, sp_out / name, exclude_dirs=["__pycache__", "tests"])
        elif src.is_file():
            (sp_out / name).write_bytes(src.read_bytes())
        # dist-info 必须一起带：不少包在 import 时会用 importlib.metadata 读**自己的版本**
        # （真实事故：`import anthropic` → PackageNotFoundError: No package metadata
        #  was found for httpx2 —— 界面起来了但一问就崩，日志里只有 metadata 报错）。
        base = name[:-3] if name.endswith(".py") else name
        for pat in {base, base.replace("_", "-"), base.replace("_", "-").lower()}:
            for di in SP.glob(f"{pat}*.dist-info"):
                if di.name in copied_di:
                    continue
                robocopy(di, sp_out / di.name)
                copied_di.add(di.name)
    # 注意：**不要复制 .pth**。venv 里有 editable install 的 finder pth
    # （`__editable___clawd_code_*_finder.py`），带进 bundle 会把 sys.path 指回**本机源码目录**，
    # 打包版就变成"依赖开发机路径"的假独立包；pywin32.pth 又会要 pywin32_bootstrap（venv 里没有）。
    # 需要的包应该在白名单里显式列出，而不是靠 pth 挂路径。

    print("[3/4] 项目源码 + prompts + Web UI")
    robocopy(ROOT / "src", OUT / "src", exclude_dirs=["__pycache__"])
    # prompts/ 必须一起打：`clawd review` 的角色模板来自 prompts/agents/*.md。
    # 实测：只带 src 时打包态执行 `clawd review` 报 ModuleNotFoundError: prompts（2026-10-29 真实发现）
    if (ROOT / "prompts").is_dir():
        robocopy(ROOT / "prompts", OUT / "prompts", exclude_dirs=["__pycache__"])
    else:
        print("  !! 警告：prompts/ 不存在，clawd review 在打包态将不可用")
    # personas/ 同理：桌面端的角色选择器读的就是这个目录（装出来没有 = 角色库是空的）
    if (ROOT / "personas").is_dir():
        robocopy(ROOT / "personas", OUT / "personas", exclude_dirs=["__pycache__"])
    else:
        print("  !! 警告：personas/ 不存在，桌面端角色库在打包态将为空")
    # Web UI（Host 同端口托管；壳 loadURL 指向 Host）
    web_out = OUT / "desktop" / "web"
    web_out.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "desktop" / "web").iterdir():
        if f.is_file():
            (web_out / f.name).write_bytes(f.read_bytes())

    print("[4/4] 配置")
    for f in ["pyproject.toml", "requirements.txt"]:
        if (ROOT / f).exists():
            (OUT / f).write_bytes((ROOT / f).read_bytes())

    # [5/5] 自检 + 缺依赖自动补齐：用**打包后的解释器**真的跑一次
    # ------------------------------------------------------------------
    # 真实事故（两次，都是装到机器上才发现）：
    #   1. 双击没反应 → `No module named 'annotated_doc'`（typer 的间接依赖）
    #   2. 界面起来了但一问就报「请安装 openai 包」→ 实际缺的是 `exceptiongroup`
    #      （anyio 在 py3.10 的依赖，而这个 venv 里 anyio 的 METADATA **没有 Requires-Dist**，
    #       所以靠 `pip show` 推闭包永远推不出来）
    # 结论：**不能只信元数据**。这里按"真实 import 能不能过"来判定，缺什么补什么，
    # 补不齐就中断打包 —— 绝不让坏 bundle 流到安装包。
    print("[5/5] 自检：内嵌解释器真实 import + 起 CLI（缺依赖自动补齐）")
    py_exe = py_out / "python.exe"
    sp_out = py_out / "Lib" / "site-packages"

    # 先准备 probe 清单：只放 venv 里确实有的包（否则永远补不齐、白白中断）
    probes: list[tuple[str, str]] = [("import typer/rich/click", "import typer, rich, click")]
    for pkg_import in (
        "openai", "anthropic", "litellm", "httpx", "tiktoken", "websockets",
        "aiohttp", "pydantic", "pydantic_settings", "loguru", "psutil", "toml",
        # 延迟 import 的功能依赖（AST 扫不到，但用户会在 CLI/桌面端用到）
        "celery", "redis", "git", "jedi", "pyflakes",
    ):
        if (SP / pkg_import).exists() or (SP / f"{pkg_import}.py").exists():
            probes.append((f"import {pkg_import}", f"import {pkg_import}"))
    probes.append(("import src.cli.entrypoint", "import src.cli.entrypoint"))
    probes.append(("import src.server", "import src.server"))

    added: list[str] = []
    max_rounds = 30
    for round_no in range(1, max_rounds + 1):
        failure: tuple[str, str] | None = None  # (label, missing module)
        for label, stmt in probes:
            r = subprocess.run(
                [str(py_exe), "-c", stmt + "; print('ok')"],
                cwd=str(OUT), capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "ENABLE_FILE_LOGGING": "false", "CLAWD_DISABLE_SESSION_PERSIST": "1"},
            )
            if r.returncode == 0:
                continue
            err = (r.stderr or "") + (r.stdout or "")
            m = re.search(r"No module named '([A-Za-z0-9_.]+)'", err)
            if not m:
                tail = err.strip().splitlines()[-6:]
                print(f"  !! 自检失败（{label}，非缺依赖）rc={r.returncode}")
                for line in tail:
                    print(f"     {line}")
                raise SystemExit(f"bundle 自检失败：{label}（入口或代码坏了，先修再打包）")
            failure = (label, m.group(1).split(".")[0])
            break
        if failure is None:
            print(f"  全部 probe 通过（补齐 {len(added)} 个包：{', '.join(added) if added else '无'}）")
            break

        label, missing = failure
        src_dir = SP / missing
        src_file = SP / f"{missing}.py"
        if src_dir.is_dir():
            robocopy(src_dir, sp_out / missing, exclude_dirs=["__pycache__", "tests"])
        elif src_file.is_file():
            (sp_out / src_file.name).write_bytes(src_file.read_bytes())
        else:
            raise SystemExit(
                f"打包缺 `{missing}`（{label} 触发），但 venv 里也没有 —— "
                f"requirements/环境不一致，先 pip install 再打包"
            )
        # dist-info 一并带上（部分包的 resources/元数据在 import 时要读）
        for di in SP.glob(f"{missing.replace('_', '-')}*.dist-info"):
            if (sp_out / di.name).exists():
                continue
            robocopy(di, sp_out / di.name)
        added.append(missing)
        print(f"  + 补齐缺失依赖: {missing}（第 {round_no} 轮，{label}）")
    else:
        raise SystemExit(f"补齐 {max_rounds} 轮仍未收敛，放弃打包（缺: {added[-5:]}）")

    # 最后再跑一次真正的 CLI 入口（import 通过不代表 typer 应用能组装）
    r = subprocess.run(
        [str(py_exe), "-m", "src", "--help"],
        cwd=str(OUT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "ENABLE_FILE_LOGGING": "false", "CLAWD_DISABLE_SESSION_PERSIST": "1"},
    )
    if r.returncode != 0:
        tail = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()[-8:]
        print(f"  !! CLI --help 失败 rc={r.returncode}")
        for line in tail:
            print(f"     {line}")
        raise SystemExit("bundle 自检失败：`-m src --help` 跑不通")
    print("  OK clawd CLI --help")

    # 工具链探针：真实执行一次 FileReadTool。
    # 为什么放这里：装机 E2E 里"让模型读文件"的结果取决于**模型是否愿意调工具**，
    # 不可控也不可复现（实测 step-5-preview 会回"我没有可用的 FileReadTool"，而工具其实注册了 7 个）。
    # 工具本体能不能跑属于确定性事实，必须在这里钉住。
    tool_probe = (
        "from pathlib import Path;"
        "from src.tools_runtime.file_read_tool import FileReadTool;"
        "r = FileReadTool(base_path=Path.cwd()).execute(file_path='pyproject.toml', limit=3);"
        "assert r.success, f'tool failed: {r.error}';"
        "print('tool ok')"
    )
    r = subprocess.run(
        [str(py_exe), "-c", tool_probe],
        cwd=str(OUT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "ENABLE_FILE_LOGGING": "false", "CLAWD_DISABLE_SESSION_PERSIST": "1"},
    )
    if r.returncode != 0 or "tool ok" not in (r.stdout or ""):
        tail = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()[-6:]
        print("  !! 工具链自检失败（FileReadTool 在打包态跑不通）")
        for line in tail:
            print(f"     {line}")
        raise SystemExit("bundle 自检失败：工具执行链路不可用")
    print("  OK FileReadTool 真实执行")

    # 自检跑过 CLI，可能在 bundle 里留下运行期数据（.clawd/logs、端口文件）——
    # 这些一旦打进安装包，用户拿到的就是"别人机器上的日志"，必须清掉。
    for junk in (OUT / ".clawd", OUT / ".clawd_host_port"):
        if junk.is_dir():
            rmtree_with_retry(junk)
        elif junk.exists():
            junk.unlink()

    size_mb = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1_048_576
    print(f"\n完成 → {OUT}  ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
