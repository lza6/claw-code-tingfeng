"""准备桌面端打包的 host/ — 白名单复制（只带真实依赖）

用法: venv/Scripts/python.exe scripts/prepare_host_bundle.py
依赖解析: AST 扫 src 的 import → venv site-packages 直接匹配 → 白名单
"""
from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "desktop" / "host"
VENV = ROOT / "venv"
SP = VENV / "Lib" / "site-packages"

# AST 扫描出的直接依赖 + 人工补的传递依赖（实测 litellm/openai/pydantic 链）
WHITELIST_EXTRA = {
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
}


def resolve_transitive(seed_names: set[str]) -> set[str]:
    """用 pip show 递归解析传递依赖（Requires 字段），直到闭包稳定。

    dist-info 的拓扑比 import 名可靠（处理了横杠/下划线归一）。
    """
    closed = set(seed_names)
    frontier = set(seed_names)
    while frontier:
        query = ",".join(sorted(frontier))
        r = subprocess.run(
            [str(VENV / "Scripts" / "python.exe"), "-m", "pip", "show", *sorted(frontier)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if r.stdout is None:
            break
        nxt: set[str] = set()
        cur: str | None = None
        for line in r.stdout.splitlines():
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
                                    entry = (SP / cand) if (SP / cand).exists() else Path(f"{cand}.py")
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
    for item in ["python.exe", "pythonw.exe", "python310.dll", "python310.zip",
                 "vcruntime140.dll", "vcruntime140_1.dll", "libcrypto-3.dll",
                 "libssl-3.dll", "libffi-8.dll", "sqlite3.dll"]:
        src = sys_base / item
        if src.exists():
            (py_out / item).write_bytes(src.read_bytes())
    robocopy(sys_base / "DLLs", py_out / "DLLs")
    robocopy(sys_base / "Lib", py_out / "Lib",
             exclude_dirs=["__pycache__", "idlelib", "tkinter", "turtledemo", "test", "site-packages"])

    print("[2/4] site-packages 白名单复制")
    whitelist = collect_whitelist()
    print(f"  白名单 {len(whitelist)} 个包")
    sp_out = py_out / "Lib" / "site-packages"
    sp_out.mkdir(parents=True, exist_ok=True)
    for name in sorted(whitelist):
        src = SP / name
        if src.is_dir():
            robocopy(src, sp_out / name, exclude_dirs=["__pycache__", "tests"])
        elif src.is_file():
            (sp_out / name).write_bytes(src.read_bytes())

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

    size_mb = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1_048_576
    print(f"\n完成 → {OUT}  ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
