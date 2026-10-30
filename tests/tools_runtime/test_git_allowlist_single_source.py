"""「git 只读子命令」清单必须**单一来源**（P3 项 2 回归）

真实缺陷（v0.88.10 报告 §5 P3）：
- `src/core/security/allowlist.py` 有一份 **18 项**（含 shortlog / reflog / whatchanged /
  show-ref / for-each-ref / name-rev）；
- `src/tools_runtime/bash_security.py` 又自己写了 **12 项**副本。

于是同一条 `git show-ref` 在 bash 工具的 `is_shell_command_read_only()` 里被判"只读、
可以执行"，换到（或将来改由）core 的 `validate_command()` 走白名单时结论又不同 ——
两套安全判定各说各话。现在 core 导出公开名 `READ_ONLY_GIT_SUBCOMMANDS`，
tools_runtime 只 import 它（tools_runtime → core 是允许的依赖方向），不再有第二份字面量。
"""

from __future__ import annotations

from src.core.security import allowlist as core_allowlist
from src.tools_runtime import bash_security

#: 修复前只在 core 侧存在的那批子命令
PREVIOUSLY_MISSING = (
    "shortlog",
    "reflog",
    "whatchanged",
    "show-ref",
    "for-each-ref",
    "name-rev",
)


class TestSingleSourceOfTruth:
    def test_tools_runtime_binds_the_core_object_itself(self):
        """不是"值相等"，而是**同一个对象**（副本会再次漂移）"""
        assert (
            bash_security.READ_ONLY_GIT_SUBCOMMANDS
            is core_allowlist.READ_ONLY_GIT_SUBCOMMANDS
        )

    def test_core_exports_public_name_and_keeps_private_alias(self):
        public = core_allowlist.READ_ONLY_GIT_SUBCOMMANDS
        assert isinstance(public, frozenset)
        # 内部老引用名仍在，且指向同一份数据（改名不打断内部用法）
        assert core_allowlist._READ_ONLY_GIT_SUBCOMMANDS is public

    def test_both_sides_contain_the_previously_missing_subcommands(self):
        for sub in PREVIOUSLY_MISSING:
            assert sub in core_allowlist.READ_ONLY_GIT_SUBCOMMANDS, sub
            assert sub in bash_security.READ_ONLY_GIT_SUBCOMMANDS, sub

    def test_same_size_and_members(self):
        assert (
            bash_security.READ_ONLY_GIT_SUBCOMMANDS
            == core_allowlist.READ_ONLY_GIT_SUBCOMMANDS
        )
        assert len(bash_security.READ_ONLY_GIT_SUBCOMMANDS) == 18


class TestValidationAgrees:
    """跑真实的校验函数，证明两边对同一条命令给出同一结论"""

    def test_git_log_like_commands_allowed_by_both(self):
        from src.core.security.allowlist import validate_command

        for args in (["log", "-1"], ["show-ref"], ["shortlog", "-sn"], ["for-each-ref"]):
            cmdline = "git " + " ".join(args)

            assert bash_security.is_shell_command_read_only(cmdline) is True, cmdline
            assert validate_command("git", args).is_valid is True, cmdline

    def test_write_subcommands_rejected_by_both(self):
        from src.core.security.allowlist import validate_command

        for args in (["commit", "-m", "x"], ["push"], ["reset", "--hard"]):
            cmdline = "git " + " ".join(args)

            assert bash_security.is_shell_command_read_only(cmdline) is False, cmdline
            assert validate_command("git", args).is_valid is False, cmdline
