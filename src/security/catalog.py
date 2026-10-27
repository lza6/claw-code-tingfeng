"""安全工具 Catalog — YAML 数据驱动的安全工具注册表（参考 hackingtool schema）

工具目录: src/security/catalog/*.yaml
每个条目声明: name / description / category / command(模板) / tags / requires_approval
SafeCatalogRunner: 目录加载 + 按模板拼装命令 + subprocess 执行（scope 授权门禁）

仅限授权测试场景使用：执行前必须 set_scope() 声明授权目标。
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CatalogError(Exception):
    pass


class ScopeNotAuthorizedError(CatalogError):
    """未声明授权 scope 就尝试执行安全工具"""


@dataclass
class CatalogEntry:
    """一条工具目录条目"""
    name: str
    description: str
    category: str
    command: str  # 模板，支持 {target} {port} {extra} 占位符
    tags: list[str] = field(default_factory=list)
    requires_approval: bool = False
    dangerous: bool = False  # 主动攻击类（扫描/爆破），默认拒绝执行
    binary: str = ""  # 实际可执行文件（默认取 command 首词）

    @classmethod
    def from_dict(cls, d: dict[str, Any], source: str = "") -> "CatalogEntry":
        for req in ("name", "description", "category", "command"):
            if req not in d:
                raise CatalogError(f"条目缺少必需字段 {req}: {source}")
        return cls(
            name=d["name"],
            description=d["description"],
            category=d["category"],
            command=d["command"],
            tags=list(d.get("tags", [])),
            requires_approval=bool(d.get("requires_approval", False)),
            dangerous=bool(d.get("dangerous", False)),
            binary=d.get("binary", d["command"].split()[0]),
        )


def load_catalog(catalog_dir: str | Path | None = None) -> list[CatalogEntry]:
    """加载全部 YAML 目录文件"""
    import yaml

    if catalog_dir is None:
        catalog_dir = Path(__file__).parent / "catalog"
    catalog_dir = Path(catalog_dir)
    entries: list[CatalogEntry] = []
    if not catalog_dir.exists():
        return entries
    for yf in sorted(catalog_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8")) or []
        except yaml.YAMLError as e:
            raise CatalogError(f"YAML 解析失败 {yf}: {e}") from e
        if not isinstance(data, list):
            raise CatalogError(f"目录文件应为条目列表: {yf}")
        for item in data:
            entries.append(CatalogEntry.from_dict(item, source=str(yf)))
    return entries


class SafeCatalogRunner:
    """安全目录执行器：scope 门禁 + 危险工具拦截 + 命令模板渲染"""

    # 危险模式：渲染后的命令含这些即拒绝（防注入到无关目标）
    _INJECTION_PATTERNS = re.compile(r"[;&|`$><]")

    def __init__(self, entries: list[CatalogEntry] | None = None):
        self.entries = entries if entries is not None else load_catalog()
        self._by_name = {e.name: e for e in self.entries}
        self._scope: set[str] = set()
        self._allow_dangerous = False

    # ---------- 授权 ----------
    def set_scope(self, targets: list[str]) -> None:
        """声明授权测试目标（IP/域名/CIDR）。未声明则任何执行都会被拒。"""
        self._scope = set(targets)
        logger.info(f"scope 已设置: {sorted(self._scope)}")

    def allow_dangerous(self, allow: bool) -> None:
        """是否允许主动攻击类工具（默认 False）"""
        self._allow_dangerous = allow

    # ---------- 查询 ----------
    def search(self, query: str) -> list[CatalogEntry]:
        q = query.lower()
        return [
            e for e in self.entries
            if q in e.name.lower() or q in e.description.lower()
            or q in e.category.lower() or q in e.tags
        ]

    def by_category(self) -> dict[str, list[str]]:
        cats: dict[str, list[str]] = {}
        for e in self.entries:
            cats.setdefault(e.category, []).append(e.name)
        return cats

    # ---------- 执行 ----------
    def render_command(self, entry: CatalogEntry, **params: str) -> str:
        """渲染命令模板并校验注入"""
        allowed = {"target", "port", "extra", "output"}
        bad = set(params) - allowed
        if bad:
            raise CatalogError(f"不允许的参数: {bad}")
        cmd = entry.command
        for k, v in params.items():
            if self._INJECTION_PATTERNS.search(v):
                raise CatalogError(f"参数含非法字符: {k}={v!r}")
            cmd = cmd.replace("{" + k + "}", v)
        # 占位符必须全部填上
        leftover = re.findall(r"\{(\w+)\}", cmd)
        if leftover:
            raise CatalogError(f"缺少参数: {leftover}")
        return cmd

    def run(self, tool_name: str, **params: str) -> str:
        """执行目录中的工具，返回 stdout（同步，超时 120s）"""
        entry = self._by_name.get(tool_name)
        if entry is None:
            raise CatalogError(f"工具不存在: {tool_name}")
        if not self._scope:
            raise ScopeNotAuthorizedError(
                "未设置授权 scope。先调用 set_scope([...]) 声明授权目标。"
                "仅限对授权资产进行测试。"
            )
        if entry.dangerous and not self._allow_dangerous:
            raise CatalogError(
                f"{tool_name} 是主动攻击类工具，需要 allow_dangerous(True) 且确认授权"
            )
        # target 必须在 scope 内（先于 binary 检查，保证 scope 门禁优先）
        target = params.get("target", "")
        if target and not self._target_in_scope(target):
            raise ScopeNotAuthorizedError(
                f"目标 {target} 不在授权 scope 内: {sorted(self._scope)}"
            )
        binary = shutil.which(entry.binary)
        if binary is None:
            raise CatalogError(f"工具未安装: {entry.binary}")

        cmd = self.render_command(entry, **params)
        logger.info(f"执行安全工具: {cmd}")
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=120, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired as e:
            raise CatalogError(f"执行超时: {tool_name}") from e
        if proc.returncode != 0 and not proc.stdout:
            raise CatalogError(
                f"执行失败 (exit {proc.returncode}): {proc.stderr[:500]}"
            )
        return proc.stdout

    def _target_in_scope(self, target: str) -> bool:
        t = target.lower().strip()
        for s in self._scope:
            s = s.lower().strip()
            if t == s or t.endswith("." + s) or t.endswith(s):
                return True
            # CIDR
            if "/" in s:
                try:
                    import ipaddress

                    ip = ipaddress.ip_address(t)
                    if ip in ipaddress.ip_network(s, strict=False):
                        return True
                except ValueError:
                    continue
        return False
