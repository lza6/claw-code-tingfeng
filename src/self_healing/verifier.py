"""验证器 — 验证修复结果"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

from .models import VerificationLevel

logger = logging.getLogger(__name__)


class Verifier:
    """验证器

    验证层次:
    - L1: 语法检查 (AST 解析)
    - L2: 静态分析 (Ruff 规则)
    - L3: 单元测试 (运行相关测试)
    - L4: 集成测试 (端到端验证)
    - L5: 安全扫描 (安全问题检查)
    """

    def __init__(
        self,
        workdir: Path | None = None,
        level: VerificationLevel = VerificationLevel.L3_UNIT_TEST,
    ) -> None:
        self.workdir = workdir or Path.cwd()
        self.level = level

    async def verify(self, code: str, file_path: str = "") -> tuple[bool, str]:
        """验证代码

        参数:
            code: 修复后的代码
            file_path: 文件路径

        返回:
            (通过, 消息)
        """
        messages: list[str] = []

        # L1: 语法检查（始终执行）
        passed, msg = self._verify_syntax(code, file_path)
        if not passed:
            return False, msg
        messages.append('L1 语法检查通过')

        # L2: 静态分析
        if self.level.value >= VerificationLevel.L2_STATIC.value:
            passed, msg = self._verify_static(code, file_path)
            if not passed:
                return False, msg
            messages.append('L2 静态分析通过')

        # L3: 单元测试
        if self.level.value >= VerificationLevel.L3_UNIT_TEST.value:
            passed, msg = await self._verify_unit_test(code, file_path)
            if not passed:
                return False, msg
            messages.append('L3 单元测试通过')

        return True, '\n'.join(messages)

    def _verify_syntax(self, code: str, file_path: str) -> tuple[bool, str]:
        """L1: 语法检查"""
        try:
            ast.parse(code)
            return True, '语法正确'
        except SyntaxError as e:
            return False, f'语法错误: {e.msg} (行 {e.lineno})'

    def _verify_static(self, code: str, file_path: str) -> tuple[bool, str]:
        """L2: 静态分析（简化版）"""
        issues: list[str] = []

        # 检查常见反模式
        if 'eval(' in code or 'exec(' in code:
            issues.append('使用了不安全的 eval/exec')

        if 'except:' in code and 'except Exception:' not in code:
            issues.append('使用了 bare except')

        if 'import *' in code:
            issues.append('使用了 import *')

        if issues:
            return False, '静态分析问题: ' + '; '.join(issues)

        return True, '静态分析通过'

    async def _verify_unit_test(self, code: str, file_path: str) -> tuple[bool, str]:
        """L3: 单元测试 (v0.66: 支持影子验证)"""
        if not file_path:
            return True, '无文件路径，跳过测试'

        # 找到对应的测试文件
        test_file = self._find_test_file(file_path)
        if not test_file:
            return True, '无对应测试文件，跳过测试'

        import asyncio
        import os
        import shutil
        import subprocess
        import tempfile

        # 创建影子验证环境 (临时替换文件运行测试)
        target_path = Path(file_path)
        if not target_path.is_absolute():
            target_path = self.workdir / target_path

        backup_path = None
        try:
            # 如果目标文件存在，先备份
            if target_path.exists():
                backup_path = Path(tempfile.mktemp(suffix='.bak', prefix='clawd_'))
                shutil.copy2(target_path, backup_path)

            # 写入待验证代码
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(code, encoding='utf-8')

            # 运行测试
            result = await asyncio.to_thread(
                subprocess.run,
                ['python', '-m', 'pytest', str(test_file), '-q', '--tb=short'],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return True, '影子测试通过'
            else:
                return False, f'影子测试失败:\n{result.stdout}\n{result.stderr}'

        except subprocess.TimeoutExpired:
            return False, '测试超时'
        except Exception as e:
            return False, f'验证过程出错: {e}'
        finally:
            # 恢复备份 (无论验证成功与否，都要恢复，因为正式写入由 Patcher 负责)
            if backup_path and backup_path.exists():
                shutil.copy2(backup_path, target_path)
                os.remove(backup_path)
            elif target_path.exists() and not backup_path:
                # 如果原本没有文件，影子测试创建了它，则删除
                os.remove(target_path)

    def _find_test_file(self, file_path: str) -> Path | None:
        """查找对应的测试文件"""
        # 将 src/module.py 转为 tests/test_module.py
        path = Path(file_path)

        # 尝试 tests 目录
        tests_dir = self.workdir / 'tests'
        if tests_dir.exists():
            # 尝试 test_<name>.py
            test_name = f'test_{path.stem}.py'
            test_file = tests_dir / test_name
            if test_file.exists():
                return test_file

            # 尝试 <name>_test.py
            test_name = f'{path.stem}_test.py'
            test_file = tests_dir / test_name
            if test_file.exists():
                return test_file

            # 递归查找
            for f in tests_dir.rglob(f'test_{path.stem}.py'):
                return f

        return None
