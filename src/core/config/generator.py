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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import toml

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ==================== 数据结构 ====================

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

# MCP 服务器定义 (参考 oh-my-codex-main/src/config/)
DEFAULT_MCP_SERVERS = {
    "clawd-state": MCPConfig(
        name="clawd-state",
        command="python",
        args=["-m", "src.core.mcp.state_server"],
        description="项目状态持久化服务器 (Surface管理)",
    ),
    "clawd-memory": MCPConfig(
        name="clawd-memory",
        command="python",
        args=["-m", "src.core.mcp.memory_server"],
        description="长期记忆存储服务器",
    ),
    "clawd-trace": MCPConfig(
        name="clawd-trace",
        command="python",
        args=["-m", "src.core.mcp.trace_server"],
        description="执行追踪服务器",
    ),
    "clawd-team": MCPConfig(
        name="clawd-team",
        command="python",
        args=["-m", "src.core.mcp.team_server"],
        description="团队协调服务器",
    ),
    "clawd-code-intel": MCPConfig(
        name="clawd-code-intel",
        command="python",
        args=["-m", "src.core.mcp.code_intel_server"],
        description="代码智能服务器 (符号/依赖)",
    ),
}


# ==================== 配置生成器 ====================

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
            category=frontmatter.get("category") or frontmatter.get("categories", [""])[0],
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

    def generate_tool_signatures(self) -> list[dict[str, Any]]:
        """生成工具签名列表 (用于 LLM function calling)"""
        # 这里应该扫描 tools_runtime/ 下的所有 Tool 类
        # 返回它们的 JSON Schema
        # 简化版本: 返回已知工具的签名
        from src.tools_runtime.tool_manager import TOOL_REGISTRY

        signatures = []
        for tool_name, tool_class in TOOL_REGISTRY.items():
            try:
                signatures.append(tool_class.get_signature())
            except Exception:
                pass
        return signatures

    def merge_into_codex_config(
        self,
        codex_config_path: Path | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """合并生成的内容到现有 Codex config.toml

        Args:
            codex_config_path: Codex config.toml 路径 (默认 ~/.claude/config.toml)
            dry_run: 只返回合并后的配置，不写入文件

        Returns:
            合并后的完整配置字典
        """
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

        # 7. 生成配置报告
        report = self._generate_report(skills, merged, dry_run)
        logger.info(f"Config generation complete:\n{report}")

        return merged

    def _generate_report(
        self,
        skills: list[SkillDefinition],
        config: dict[str, Any],
        dry_run: bool,
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
) -> None:
    """CLI 命令: clawd config generate

    用法:
        clawd config generate                    # 生成并写入默认路径
        clawd config generate --path ~/.claude/config.toml
        clawd config generate --dry-run          # 预览合并结果
    """
    generator = ConfigGenerator(project_root=Path.cwd())

    if verbose:
        logger.setLevel("DEBUG")
    else:
        logger.setLevel("INFO")

    try:
        config = generator.merge_into_codex_config(
            codex_config_path=config_path,
            dry_run=dry_run,
        )

        if dry_run:
            print("\n[预览模式] 合并后的配置:")
            print(toml.dumps(config))
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
    "ConfigGenerator",
    "MCPConfig",
    "SkillDefinition",
    "config_generate_command",
    "setup_cli_commands",
]
