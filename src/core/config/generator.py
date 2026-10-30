"""动态配置生成器 - 整合技能、工具、表面、代理到Codex配置

此模块借鉴 oh-my-codex-main/src/config/generator.ts 的设计:
- 自动发现并注册 skills
- 生成 MCP 服务器配置
- 注入 CLawd Code 特有的配置到 Codex config.toml
- 生成 AGENTS.md 覆盖

输出: ~/.claude/config.toml (或项目本地 .clawd/config.toml)
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import toml
import typer

from src.utils.file_ops import atomic_write_json
from src.utils.logger import get_logger

logger = get_logger(__name__)

#: 工具签名落盘文件名：写在**目标配置目录**（与 config.toml 同级），不进 config.toml
TOOL_SIGNATURES_FILE = "tool_signatures.json"

#: dry-run 时签名"写不出去"，改为放进返回 dict 的这个独立键。
#: 取一个不会与 codex config 既有键（features / mcp_servers / notify …）撞名的名字，
#: 且**永远不写入 config.toml**（写盘前就把它剔掉），避免污染用户配置。
TOOL_SIGNATURES_PREVIEW_KEY = "__tool_signatures__"


# ==================== 数据结构 ====================

def _first_category(frontmatter: dict[str, Any]) -> str:
    """取技能的 category（容忍 `categories: []` / `categories: a, b` 等写法）

    真实缺陷：原来是 `frontmatter.get("category") or frontmatter.get("categories", [""])[0]`
    —— YAML 写 `categories: []` 时 get 返回**空列表**（不是默认值），`[][0]` 抛 IndexError，
    被 `discover_skills` 的 except 吞掉 → 该技能**静默消失**，用户完全不知道。
    """
    cat = frontmatter.get("category")
    if cat:
        return str(cat).strip()
    cats = frontmatter.get("categories")
    if isinstance(cats, (list, tuple)):
        for item in cats:
            text = str(item).strip()
            if text:
                return text
        return ""
    if isinstance(cats, str):
        return cats.strip()
    return ""


@dataclass
class SkillDefinition:
    """技能定义"""
    name: str
    description: str
    intent: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    filepath: Path | None = None


@dataclass
class MCPConfig:
    """MCP 服务器配置"""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""


# ==================== OMX 风格的配置模板 ====================

# 默认注入到 Codex config.toml 的配置块
DEFAULT_OMX_CONFIG = """
# Clawd Code / OMX 扩展配置
# 此部分由 clawd config generate 自动生成

[features]
# 功能开关
persistence = true          # 持久化执行 (Ralph)
team_mode = true           # 团队模式
worktree_isolation = true  # 工作树隔离
self_fission = true        # 自我合成
quality_gate = true        # 质量门控
budget_guard = true        # 预算守卫

[mcp_servers]
# MCP 服务器列表 - 由 generator 动态填充
"""

# MCP 服务器用的解释器：必须是**当前正在运行 clawd 的那个 Python**
# （本机裸 `python` 指向 3.14，缺 loguru 等运行依赖，spawn 起来会立刻失败）
MCP_PYTHON = sys.executable or "python"

# MCP 服务器定义 (参考 oh-my-codex-main/src/config/)
DEFAULT_MCP_SERVERS = {
    "clawd-state": MCPConfig(
        name="clawd-state",
        command=MCP_PYTHON,
        args=["-m", "src.core.mcp.state_server"],
        description="项目状态持久化服务器 (Surface管理)",
    ),
    "clawd-memory": MCPConfig(
        name="clawd-memory",
        command=MCP_PYTHON,
        args=["-m", "src.core.mcp.memory_server"],
        description="长期记忆存储服务器",
    ),
    "clawd-trace": MCPConfig(
        name="clawd-trace",
        command=MCP_PYTHON,
        args=["-m", "src.core.mcp.trace_server"],
        description="执行追踪服务器",
    ),
    "clawd-team": MCPConfig(
        name="clawd-team",
        command=MCP_PYTHON,
        args=["-m", "src.core.mcp.team_server"],
        description="团队协调服务器",
    ),
    # 注意：这里原先还有一条 "clawd-code-intel"，指向
    # `src.core.mcp.code_intel_server` —— 该文件从未存在（真实实现在
    # `src.mcp.code_intel`，且该模块已被删除，能力由
    # tools_runtime.ast_grep_tool / symbol_find_tool 覆盖）。
    # 生成一条指向不存在模块的配置，等于给用户一个必然启动失败的 MCP 服务器，
    # 故移除。若将来要恢复代码智能服务器，需先落地真实模块再登记。
}


# ==================== 配置生成器 ====================

_JSON_TYPE_BY_PARAM = {
    "str": "string", "int": "integer", "float": "number", "bool": "boolean",
    "list": "array", "dict": "object",
}


def _tool_signature(tool: Any) -> dict[str, Any] | None:
    """把工具对象转成 LLM function-calling 的签名

    优先用工具自带的 `get_signature()`；没有就用通用的
    `name` / `description` / `parameters`（`ParameterSchema` 列表）组装 ——
    仓库里绝大多数工具的形态是后者（例如 `FileReadTool`），
    只认 `get_signature()` 会让"真实工具"一个都产不出签名（实测）。
    """
    getter = getattr(tool, "get_signature", None)
    if callable(getter):
        sig = getter()
        if sig:
            return sig
    name = str(getattr(tool, "name", "") or "")
    if not name:
        return None
    properties: dict[str, Any] = {}
    required: list[str] = []
    # 真实形态是 `parameter_schemas`（tuple[ParameterSchema, ...]），
    # `parameters` 只是个别工具的自定义名 —— 两个都认
    raw_params = getattr(tool, "parameters", None) or getattr(tool, "parameter_schemas", None) or []
    for param in raw_params:
        pname = str(getattr(param, "name", "") or "")
        if not pname:
            continue
        properties[pname] = {
            "type": _JSON_TYPE_BY_PARAM.get(str(getattr(param, "param_type", "str") or "str"), "string"),
            "description": str(getattr(param, "description", "") or ""),
        }
        if getattr(param, "required", False):
            required.append(pname)
    return {
        "name": name,
        "description": str(getattr(tool, "description", "") or ""),
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


class ConfigGenerator:
    """动态配置生成器

    职责:
    1. 扫描 skills/ 目录，发现可用技能
    2. 扫描 agents/ 目录，生成角色定义
    3. 收集工具签名 (用于 LLM function calling)
    4. 生成 MCP 服务器配置
    5. 合并到现有 Codex config.toml

    参考: oh-my-codex-main/src/config/generator.ts
    """

    def __init__(
        self,
        project_root: Path | None = None,
        claude_config_dir: Path | None = None,
    ):
        self.project_root = project_root or Path.cwd()
        self.claude_config_dir = claude_config_dir or self._find_claude_config()
        self.skills_dir = self.project_root / "skills"
        self.agents_dir = self.project_root / "agents"

    def _find_claude_config(self) -> Path:
        """查找 Claude Code 配置目录"""
        # Codex 使用 ~/.claude
        home = Path.home()
        candidates = [
            home / ".claude",
            home / ".config" / "claude",
            self.project_root / ".clawd",
        ]
        for p in candidates:
            if p.exists():
                return p
        return home / ".claude"

    def discover_skills(self) -> list[SkillDefinition]:
        """扫描 skills/ 目录，发现所有技能"""
        skills = []
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return skills

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                skill = self._parse_skill_md(skill_md, skill_dir)
                skills.append(skill)
            except Exception as e:
                logger.error(f"Failed to parse skill {skill_dir.name}: {e}")

        logger.info(f"Discovered {len(skills)} skills")
        return skills

    def _parse_skill_md(self, skill_md: Path, skill_dir: Path) -> SkillDefinition:
        """解析 SKILL.md (支持 YAML frontmatter)"""
        content = skill_md.read_text(encoding="utf-8")

        # 提取 YAML frontmatter
        frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if frontmatter_match:
            import yaml
            frontmatter = yaml.safe_load(frontmatter_match.group(1))
        else:
            # 旧格式: --- name: xxx\ndescription: xxx ---
            frontmatter = {}

        return SkillDefinition(
            name=frontmatter.get("name", skill_dir.name),
            description=frontmatter.get("description", ""),
            intent=frontmatter.get("intent"),
            category=_first_category(frontmatter),
            tags=frontmatter.get("tags", []),
            filepath=skill_md,
        )

    def generate_agents_override(self, skills: list[SkillDefinition]) -> str:
        """生成 AGENTS.md 覆盖内容

        将技能映射为可被 Claude Code 调用的 agent role。
        """
        lines = [
            "# Clawd Code - Agent Roles (Auto-generated)\n",
            "此文件由 `clawd config generate` 自动生成，包含所有可用 agent 角色。\n",
            "## Agent Roles\n\n",
        ]

        for skill in skills:
            # 将技能转换为 agent role
            role_name = skill.name.replace("-", "_")
            lines.append(f"### {role_name}\n")
            lines.append(f"{skill.description}\n\n")
            if skill.tags:
                lines.append(f"**Tags**: {', '.join(skill.tags)}\n\n")
            if skill.intent:
                lines.append(f"**Intent**: {skill.intent}\n\n")
            lines.append("---\n\n")

        return "".join(lines)

    def generate_mcp_config(self) -> dict[str, Any]:
        """生成 MCP 服务器配置片段 (用于 Codex config.toml)"""
        mcp_servers = {}
        for name, server in DEFAULT_MCP_SERVERS.items():
            # 替换 PYTHONPATH 等环境变量
            env = {**server.env, "PYTHONPATH": str(self.project_root)}
            mcp_servers[name] = {
                "command": server.command,
                "args": server.args,
                "env": env,
                "description": server.description,
            }
        return mcp_servers

    def generate_omx_features(self) -> dict[str, Any]:
        """生成 OMX features 配置片段"""
        return {
            "features": {
                "persistence": True,
                "team_mode": True,
                "worktree_isolation": True,
                "self_fission": True,
                "quality_gate": True,
                "budget_guard": True,
                "mcp_servers": True,
            },
            "notify": "echo '[Clawd] {event}'",
            "model_reasoning_effort": "auto",
            "developer_instructions": (
                "You are Clawd Code, an advanced AI coding agent. "
                "Use tools precisely and verify before committing. "
                "Run tests after changes. Follow TDD workflow."
            ),
        }

    def generate_tool_signatures(self, tools: Any | None = None) -> list[dict[str, Any]]:
        """生成工具签名列表 (用于 LLM function calling)

        `tools` 由**调用方注入**（`dict[name, Tool]` 或 Tool 实例的可迭代）。
        工具清单是上层概念，core 不该 import `tools_runtime`（core 边界治理，
        见 `scripts/core_surface.py`）；不传就返回空列表，而不是偷偷依赖一个不存在的模块。

        真实缺陷：原实现 `from src.tools_runtime.tool_manager import TOOL_REGISTRY` ——
        该模块全仓库都不存在（注册表实为 `src/tools_runtime/registry.py` 的 `ToolRegistry` 类），
        所以这个方法只要被调用就必然抛 ModuleNotFoundError（测试里 xfail 记着）。
        """
        if tools is None:
            return []
        items = list(tools.values()) if isinstance(tools, dict) else list(tools)
        signatures: list[dict[str, Any]] = []
        for tool in items:
            try:
                sig = _tool_signature(tool)
                if sig:
                    signatures.append(sig)
            except Exception as exc:  # noqa: BLE001 — 单个工具自省失败不能中断整体
                logger.debug(f"工具签名收集失败（已跳过）: {exc}")
        return signatures

    def merge_into_codex_config(
        self,
        codex_config_path: Path | None = None,
        dry_run: bool = False,
        tool_signatures: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """合并生成的内容到现有 Codex config.toml

        Args:
            codex_config_path: Codex config.toml 路径 (默认 ~/.claude/config.toml)
            dry_run: 只返回合并后的配置，不写入文件
            tool_signatures: 上层注入的工具签名（见 `generate_tool_signatures`）。
                非 dry-run 时落到 `tool_signatures.json`（与 config.toml 同目录）；
                dry-run 时不写盘，改放进返回 dict 的 `TOOL_SIGNATURES_PREVIEW_KEY`。

        Returns:
            合并后的完整配置字典
        """
        signatures = list(tool_signatures or [])

        # 1. 读取现有配置 (如果存在)
        if codex_config_path is None:
            codex_config_path = self.claude_config_dir / "config.toml"

        existing_config = {}
        if codex_config_path.exists():
            try:
                existing_config = toml.load(codex_config_path)
            except Exception as e:
                logger.error(f"Failed to parse existing config: {e}")

        # 2. 发现技能
        skills = self.discover_skills()

        # 3. 生成新增内容
        omx_features = self.generate_omx_features()
        mcp_config = self.generate_mcp_config()

        # 4. 合并: existing + omx_features (优先级: omx < existing)
        merged = {**omx_features, **existing_config}

        # MCP 服务器合并 (不覆盖用户自定义 MCP)
        if "mcp_servers" not in merged:
            merged["mcp_servers"] = {}
        for name, server in mcp_config.items():
            merged["mcp_servers"].setdefault(name, server)

        # 5. 写入 AGENTS.md 覆盖
        agents_content = self.generate_agents_override(skills)
        agents_path = self.project_root / ".clawd" / "AGENTS.md"
        if not dry_run:
            agents_path.parent.mkdir(parents=True, exist_ok=True)
            agents_path.write_text(agents_content, encoding="utf-8")
            logger.info(f"Wrote AGENTS override to {agents_path}")

        # 6. 写入配置
        if not dry_run:
            codex_config_path.parent.mkdir(parents=True, exist_ok=True)
            toml_str = toml.dumps(merged)
            codex_config_path.write_text(toml_str, encoding="utf-8")
            logger.info(f"Merged config written to {codex_config_path}")

        # 6.5 工具签名：**只**落到独立的 tool_signatures.json，绝不混进 config.toml
        # （config.toml 是 codex 的配置文件，加非 codex 的键会污染它）。
        # 原子写用项目既有的 `atomic_write_json`（同目录 tmp + os.replace）。
        if signatures and not dry_run:
            signatures_path = codex_config_path.parent / TOOL_SIGNATURES_FILE
            atomic_write_json(signatures_path, signatures)
            logger.info(f"Wrote {len(signatures)} tool signatures to {signatures_path}")

        # 7. 生成配置报告
        report = self._generate_report(skills, merged, dry_run, tool_signatures=signatures)
        logger.info(f"Config generation complete:\n{report}")

        if signatures and dry_run:
            # dry-run 不写盘，但签名不能就此丢掉：调用方（CLI 预览 / 测试）要从返回值里拿到
            merged[TOOL_SIGNATURES_PREVIEW_KEY] = signatures

        return merged

    def _generate_report(
        self,
        skills: list[SkillDefinition],
        config: dict[str, Any],
        dry_run: bool,
        tool_signatures: list[dict[str, Any]] | None = None,
    ) -> str:
        """生成配置报告"""
        lines = [
            "=" * 60,
            "Clawd Code 配置生成报告",
            "=" * 60,
            "",
            f"发现技能: {len(skills)} 个",
            "",
        ]
        for skill in skills:
            lines.append(f"  - {skill.name}: {skill.description[:60]}...")

        lines.extend([
            "",
            f"MCP 服务器: {len(config.get('mcp_servers', {}))} 个",
            # 0 个也要如实写出来：以前这里没有这行，签名能力等于不存在（无调用方）
            f"工具签名: {len(tool_signatures or [])} 个",
            "",
            "功能开关:",
            *(f"  - {k}: {v}" for k, v in config.get("features", {}).items()),
            "",
            f"Dry-run: {dry_run}",
            "",
            "下一步:",
            "  1. 启动 clawd: clawd chat",
            "  2. 使用技能: $<skill-name> <args>",
            "  3. 查看团队: clawd team status",
            "",
        ])
        return "\n".join(lines)


# ==================== CLI 命令 ====================

def config_generate_command(
    config_path: Path | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    tools: Any | None = None,
) -> dict[str, Any]:
    """CLI 命令: clawd config generate

    用法:
        clawd config generate                    # 生成并写入默认路径
        clawd config generate --path ~/.claude/config.toml
        clawd config generate --dry-run          # 预览合并结果

    `tools`: 真实工具清单（`dict[name, Tool]` 或 Tool 可迭代），由 **CLI 层注入**。
    core 不能 import `tools_runtime`（`scripts/core_surface.py` 是硬门禁），
    所以工具清单只能由上往下传；不传就是 0 个签名，报告里如实写 0，不假造。
    """
    generator = ConfigGenerator(project_root=Path.cwd())

    if verbose:
        logger.setLevel("DEBUG")
    else:
        logger.setLevel("INFO")

    try:
        signatures = generator.generate_tool_signatures(tools)
        config = generator.merge_into_codex_config(
            codex_config_path=config_path,
            dry_run=dry_run,
            tool_signatures=signatures,
        )

        if dry_run:
            # 签名不是 codex config 的键，预览时单独列，别混进 toml 里装作是配置项
            preview = {
                k: v for k, v in config.items() if k != TOOL_SIGNATURES_PREVIEW_KEY
            }
            print("\n[预览模式] 合并后的配置:")
            print(toml.dumps(preview))
            print(f"[预览模式] 工具签名: {len(signatures)} 个（dry-run 不落盘）")
            for sig in signatures:
                print(f"  - {sig.get('name', '?')}")
        elif signatures:
            # 走 stderr：`config --json` 时 stdout 必须只有 JSON（`--json | jq` 不能崩）
            print(f"工具签名已写入: {len(signatures)} 个 → {TOOL_SIGNATURES_FILE}", file=sys.stderr)
        else:
            print(
                "工具签名: 0 个（CLI 层未注入工具清单，本次不写 tool_signatures.json）",
                file=sys.stderr,
            )

        return config
    except Exception as e:
        logger.error(f"Config generation failed: {e}")
        raise


def setup_cli_commands(app: typer.Typer) -> None:
    """注册配置相关 CLI 命令"""

    @app.command(name="config-generate")
    def config_generate(
        path: Path | None = typer.Option(
            None, "--path", "-p", help="输出配置文件路径"
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="预览不写入"
        ),
        verbose: bool = typer.Option(
            False, "--verbose", "-v", help="详细输出"
        ),
    ):
        """动态生成并合并 Clawd Code 配置到 Codex"""
        config_generate_command(
            config_path=path,
            dry_run=dry_run,
            verbose=verbose,
        )

    @app.command(name="config-show")
    def config_show():
        """显示当前合并后的配置"""
        generator = ConfigGenerator(project_root=Path.cwd())
        config_path = generator.claude_config_dir / "config.toml"
        if config_path.exists():
            print(config_path.read_text())
        else:
            print("配置文件不存在，运行 `clawd config generate` 创建")


__all__ = [
    "TOOL_SIGNATURES_FILE",
    "TOOL_SIGNATURES_PREVIEW_KEY",
    "ConfigGenerator",
    "MCPConfig",
    "SkillDefinition",
    "config_generate_command",
    "setup_cli_commands",
]
