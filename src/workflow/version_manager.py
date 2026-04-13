"""语义化版本管理 — pyproject.toml + CHANGELOG.md"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.exceptions import ClawdError, ErrorCode

_SEMVER_RE = re.compile(
    r'^(?P<major>0|[1-9]\d*)(?:\.(?P<minor>0|[1-9]\d*)(?:\.(?P<patch>0|[1-9]\d*))?)?'
    r'(?:-(?P<prerelease>[0-9a-zA-Z][0-9a-zA-Z.]*))?'
    r'(?:\+(?P<build>[0-9a-zA-Z]+))?$'
)


class VersionManager:
    """语义化版本管理。所有操作本地化，禁止自动打 Tag。"""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else Path.cwd()
        self.pyproject_path = self.root / 'pyproject.toml'
        self.changelog_path = self.root / 'CHANGELOG.md'

    # -- 当前版本 --

    def get_current_version(self) -> str:
        """解析 pyproject.toml 中的 version = "X.Y.Z" 字段"""
        if not self.pyproject_path.exists():
            raise ClawdError(code=ErrorCode.WORKFLOW_FILE_NOT_FOUND,
                             message=f'文件不存在: {self.pyproject_path.name}',
                             recoverable=False)
        text = self.pyproject_path.read_text(encoding='utf-8')
        match = re.search(r'^version\s*=\s*"([\d.\w-]+)"', text, re.MULTILINE)
        if not match:
            raise ClawdError(code=ErrorCode.VALIDATION_ERROR,
                             message='无法在 pyproject.toml 中找到 version 字段',
                             recoverable=False)
        return match.group(1)

    def _parse_semver(self, version: str) -> dict[str, Any]:
        """解析语义化版本字符串

        返回:
            {'major': int, 'minor': int, 'patch': int, 'prerelease': str|None}
        """
        match = _SEMVER_RE.match(version)
        if not match:
            raise ClawdError(code=ErrorCode.VALIDATION_ERROR,
                             message=f'无效的版本格式: {version}',
                             recoverable=False)

        groups = match.groupdict()
        return {
            'major': int(groups['major']),
            'minor': int(groups['minor']) if groups['minor'] is not None else 0,
            'patch': int(groups['patch']) if groups['patch'] is not None else 0,
            'prerelease': groups.get('prerelease'),
        }

    # -- 版本递增 --

    def bump(self, bump_type: str, prerelease_id: str | None = None) -> str:
        """语义化版本递增并写回 pyproject.toml

        参数:
            bump_type: major | minor | patch | prerelease
            prerelease_id: prerelease 标识符，如 'alpha', 'beta', 'rc'
        返回: 递增后的版本号
        """
        current = self.get_current_version()
        parsed = self._parse_semver(current)

        major = parsed['major']
        minor = parsed['minor']
        patch = parsed['patch']
        existing_pre = parsed['prerelease']

        if bump_type == 'major':
            major += 1
            minor = 0
            patch = 0
            new_version = f'{major}.{minor}.{patch}'
        elif bump_type == 'minor':
            minor += 1
            patch = 0
            new_version = f'{major}.{minor}.{patch}'
        elif bump_type == 'patch':
            patch += 1
            new_version = f'{major}.{minor}.{patch}' if existing_pre is None else f'{major}.{minor}.{patch}'
        elif bump_type == 'prerelease':
            tag = prerelease_id or self._detect_prerelease_tag(existing_pre)
            if existing_pre and existing_pre.startswith(tag + '.'):
                # 已有相同预热标识，递增计数器
                counter = self._extract_counter(existing_pre)
                new_version = f'{major}.{minor}.{patch}-{tag}.{counter}'
            elif existing_pre:
                # 已有预热标识但标记不同，切换标记并重置计数器
                new_version = f'{major}.{minor}.{patch}-{tag}.1'
            else:
                # 无预热标识，添加新预热
                new_version = f'{major}.{minor}.{patch}-{tag}.1'
        else:
            raise ClawdError(code=ErrorCode.VALIDATION_ERROR,
                             message=f'未知的版本类型: {bump_type}',
                             recoverable=False)

        self._update_version_in_pyproject(new_version)
        return new_version

    def _detect_prerelease_tag(self, prerelease: str | None) -> str:
        """从现有预热标识中提取 tag，默认 'alpha'"""
        if prerelease:
            return prerelease.split('.')[0]
        return 'alpha'

    def _extract_counter(self, prerelease: str) -> int:
        """从预热标识中提取计数器并返回递增后的值"""
        parts = prerelease.split('.')
        if len(parts) >= 2 and parts[-1].isdigit():
            return int(parts[-1]) + 1
        return 1

    # -- CHANGELOG --

    def update_changelog(self, version: str, categories: dict[str, list[str]]) -> Path:
        """在 CHANGELOG.md 顶部插入新版本条目"""
        if not self.changelog_path.exists():
            header = "# CHANGELOG\n\nAll notable changes to this project will be documented in this file.\n\nThe format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),\nand this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n\n"
            self.changelog_path.write_text(header, encoding='utf-8')

        content = self.changelog_path.read_text(encoding='utf-8')
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        header = f'## [{version}] - {today}'

        # 标准分类顺序
        standard_order = [
            'Added', 'Changed', 'Deprecated', 'Removed', 'Fixed', 'Security', 'Performance'
        ]

        entries: list[str] = [header, '']

        # 转换并过滤分类名（首字母大写）
        normalized_cats = {k.capitalize(): v for k, v in categories.items()}

        # 按标准顺序添加分类
        for cat in standard_order:
            if normalized_cats.get(cat):
                entries.append(f'### {cat}')
                for item in normalized_cats[cat]:
                    entries.append(f'- {item}')
                entries.append('')

        # 处理非标准分类
        for cat, items in normalized_cats.items():
            if cat not in standard_order and items:
                entries.append(f'### {cat}')
                for item in items:
                    entries.append(f'- {item}')
                entries.append('')

        # 查找插入位置（第一个 ## [ 之后）
        insert_match = re.search(r'## \[', content)
        if insert_match:
            insert_pos = insert_match.start()
            new_content = content[:insert_pos] + '\n'.join(entries) + '\n' + content[insert_pos:]
        else:
            new_content = content.rstrip() + '\n\n' + '\n'.join(entries) + '\n'

        self.changelog_path.write_text(new_content, encoding='utf-8')
        return self.changelog_path

    def bump_and_log(self, bump_type: str, categories: dict[str, list[str]],
                     prerelease_id: str | None = None) -> str:
        """原子操作：版本递增 + 更新 CHANGELOG"""
        new_version = self.bump(bump_type, prerelease_id)
        self.update_changelog(new_version, categories)
        return new_version

    # -- 一致性检查 --

    def check_consistency(self) -> tuple[bool, dict[str, Any]]:
        """对比 pyproject.toml 版本 vs CHANGELOG.md 首个版本头

        返回:
            (是否一致, 详细信息 dict)
        """
        pyproject_version = self.get_current_version()

        changelog_version = None
        if self.changelog_path.exists():
            content = self.changelog_path.read_text(encoding='utf-8')
            match = re.search(r'^## \[([\d.\w-]+)\]', content, re.MULTILINE)
            if match:
                changelog_version = match.group(1)

        if changelog_version is None:
            return (False, {
                'pyproject_version': pyproject_version,
                'changelog_version': '未找到',
                'issue': 'CHANGELOG.md 中未找到版本号',
            })

        # 全版本对比（包括预热标识）
        is_consistent = pyproject_version == changelog_version
        return (is_consistent, {
            'pyproject_version': pyproject_version,
            'changelog_version': changelog_version,
        })

    # -- 内部方法 --

    def _update_version_in_pyproject(self, new_version: str) -> None:
        """原地更新 version 字段"""
        text = self.pyproject_path.read_text(encoding='utf-8')
        new_text = re.sub(
            r'^(version\s*=\s*)"[^"]*"',
            rf'\g<1>"{new_version}"',
            text, flags=re.MULTILINE, count=1,
        )
        if new_text == text:
            new_text = re.sub(
                r'^(version\s*=\s*)\S+',
                rf'\g<1>{new_version}',
                text, flags=re.MULTILINE, count=1,
            )
            if new_text == text:
                raise ClawdError(code=ErrorCode.VALIDATION_ERROR,
                                 message='无法更新 pyproject.toml 中的版本号',
                                 recoverable=False)
        self.pyproject_path.write_text(new_text, encoding='utf-8')
