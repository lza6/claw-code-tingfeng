"""CLI `--json` 契约（高阶提案 X-7 的地基）

为什么钉住：二十多个命令组里此前只有 `reason` 支持 `--json`，其余只能人读 ——
脚本/CI 无法消费。统一契约后，`--json` 只换输出形态、**不改变退出码语义**，
且失败时也必须是合法 JSON（不能把中文错误和 JSON 拼一起，那样 `| jq` 必崩）。
"""

from __future__ import annotations

import io
import json

from src.cli.command_result import CommandResult, emit


class TestCommandResultShape:
    def test_payload_has_stable_top_level_keys(self):
        r = CommandResult(ok=True, data={"count": 3, "items": ["a"]}, human="三个")
        payload = r.to_payload()

        assert payload["ok"] is True
        assert payload["code"] == 0
        assert payload["count"] == 3
        assert payload["items"] == ["a"]
        # 契约：ok / code 永远在最外层，data 的键平铺（便于 jq '.count'）
        assert set(payload) >= {"ok", "code", "count", "items"}

    def test_code_derived_from_ok(self):
        assert CommandResult(ok=True).code == 0
        assert CommandResult(ok=False).code == 1

    def test_explicit_exit_code_wins(self):
        assert CommandResult(ok=True, exit_code=2).code == 2
        assert CommandResult(ok=False, exit_code=0).code == 0

    def test_json_is_parseable_and_utf8_readable(self):
        r = CommandResult(ok=True, data={"message": "中文不应被转义"}, human="x")
        text = r.to_json()

        assert "中文不应被转义" in text, "ensure_ascii 必须为 False（否则中文变 \\uXXXX）"
        assert json.loads(text)["message"] == "中文不应被转义"

    def test_non_serializable_data_does_not_crash(self, tmp_path):
        """路径这类对象要能序列化（否则 --json 直接抛 TypeError）"""
        r = CommandResult(ok=True, data={"path": tmp_path}, human="")
        # 注意：JSON 里反斜杠会被转义，所以解析后再比，而不是字符串包含
        assert json.loads(r.to_json())["path"] == str(tmp_path)

    def test_render_falls_back_to_json_when_human_empty(self):
        r = CommandResult(ok=True, data={"a": 1}, human="   ")
        assert json.loads(r.render())["a"] == 1


class TestEmit:
    def test_json_mode_prints_single_line_json(self):
        buf = io.StringIO()
        code = emit(CommandResult(ok=True, data={"n": 1}, human="人读正文"), as_json=True, stream=buf)

        out = buf.getvalue().strip()
        assert code == 0
        assert "\n" not in out, f"--json 必须单行: {out!r}"
        assert json.loads(out) == {"ok": True, "code": 0, "n": 1}
        assert "人读正文" not in out, "JSON 模式下不应混入人读文本"

    def test_human_mode_prints_human_text(self):
        buf = io.StringIO()
        code = emit(CommandResult(ok=True, data={"n": 1}, human="人读正文"), as_json=False, stream=buf)

        assert code == 0
        assert buf.getvalue().strip() == "人读正文"

    def test_failure_still_emits_valid_json(self):
        """失败时 --json 也必须是合法 JSON（ok=false + 中文 message）"""
        buf = io.StringIO()
        code = emit(
            CommandResult(ok=False, data={"message": "目标不存在"}, human="✖ 目标不存在"),
            as_json=True,
            stream=buf,
        )

        payload = json.loads(buf.getvalue().strip())
        assert code == 1
        assert payload["ok"] is False
        assert payload["code"] == 1
        assert payload["message"] == "目标不存在"

    def test_exit_code_consistency_between_modes(self):
        """同一结果在两种输出形态下退出码必须一致（否则脚本与人对不上）"""
        for ok in (True, False):
            buf = io.StringIO()
            code_json = emit(CommandResult(ok=ok, data={}, human="x"), as_json=True, stream=buf)
            code_human = emit(CommandResult(ok=ok, data={}, human="x"), as_json=False, stream=buf)
            assert code_json == code_human == (0 if ok else 1)
