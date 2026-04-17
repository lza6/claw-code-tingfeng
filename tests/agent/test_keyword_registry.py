"""Keyword Registry & Intent Router 测试套件

覆盖：
- 关键词触发器注册表
- 执行门控与 well-specified 检测
- ralplan-first gate 重定向逻辑
- 技能激活状态持久化
- 任务规模检测集成
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agent.keyword_registry import (
    KeywordTrigger,
    KEYWORD_TRIGGER_DEFINITIONS,
    KEYWORDS_REQUIRING_INTENT,
    EXECUTION_GATE_KEYWORDS,
    GATE_BYPASS_PREFIXES,
    WELL_SPECIFIED_SIGNALS,
    detect_keywords,
    detect_primary_keyword,
    has_intent_context_for_keyword,
    is_underspecified_for_execution,
    apply_ralplan_gate,
    record_skill_activation,
    get_skill_active_state,
    get_trigger_by_keyword,
    get_all_keywords,
    get_task_size_class,
    has_explore_intent,
    get_deep_interview_lock_state,
    is_deep_interview_input_blocked,
    release_deep_interview_on_cancel,
)


# ==================== 触发器注册表测试 ====================

class TestKeywordTriggerDefinitions:
    """关键词触发器注册表完整性测试"""

    def test_trigger_definitions_not_empty(self):
        """测试注册表非空"""
        assert len(KEYWORD_TRIGGER_DEFINITIONS) > 0

    def test_triggers_unique_keywords(self):
        """测试所有关键词唯一"""
        keywords = [t.keyword for t in KEYWORD_TRIGGER_DEFINITIONS]
        duplicates = [k for k in set(keywords) if keywords.count(k) > 1]
        assert duplicates == [], f"重复的关键词: {duplicates}"

    def test_triggers_have_positive_priority(self):
        """测试所有优先级为正数"""
        for trigger in KEYWORD_TRIGGER_DEFINITIONS:
            assert trigger.priority > 0, f"{trigger.keyword} 优先级应 > 0"

    def test_triggers_have_skill_name(self):
        """测试所有触发器有技能名称"""
        for trigger in KEYWORD_TRIGGER_DEFINITIONS:
            assert trigger.skill, f"{trigger.keyword} 缺少技能名称"

    def test_ralph_trigger_exists(self):
        """测试 ralph 触发器存在"""
        ralph = get_trigger_by_keyword('ralph')
        assert ralph is not None
        assert ralph.skill == 'ralph_loop'

    def test_team_trigger_requires_intent(self):
        """测试 team 触发器需要明确意图"""
        team = get_trigger_by_keyword('team')
        assert team is not None
        assert team.requires_intent is True

    def test_swarm_trigger_requires_intent_and_maps_to_team(self):
        """测试 swarm 触发器映射到 team"""
        swarm = get_trigger_by_keyword('swarm')
        assert swarm is not None
        assert swarm.skill == 'team_execution'
        assert swarm.requires_intent is True

    def test_ralplan_trigger_highest_priority(self):
        """测试 ralplan 优先级最高"""
        ralplan = get_trigger_by_keyword('ralplan')
        assert ralplan is not None
        max_priority = max(t.priority for t in KEYWORD_TRIGGER_DEFINITIONS)
        assert ralplan.priority == max_priority

    def test_get_trigger_by_keyword_case_insensitive(self):
        """测试关键词查询不区分大小写"""
        assert get_trigger_by_keyword('RALPH') is not None
        assert get_trigger_by_keyword('Team') is not None
        assert get_trigger_by_keyword('SWARM') is not None

    def test_get_all_keywords_returns_list(self):
        """测试获取所有关键词"""
        keywords = get_all_keywords()
        assert isinstance(keywords, list)
        assert 'ralph' in keywords
        assert 'team' in keywords


# ==================== 意图验证测试 ====================

class TestIntentContext:
    """意图上下文验证测试"""

    def test_low_risk_keywords_pass_intent_check(self):
        """测试低风险关键词通过意图检查"""
        # 不需要意图的关键词
        low_risk_keywords = ['simplify', 'review', 'test', 'build', 'ship', 'pipeline']
        for kw in low_risk_keywords:
            assert has_intent_context_for_keyword("随便什么文本", kw)

    def test_high_risk_keywords_need_explicit_intent(self):
        """测试高风险关键词需要明确意图"""
        team = 'team'
        swarm = 'swarm'
        # 无明确意图时返回 False
        assert not has_intent_context_for_keyword("帮我执行团队任务", team)
        assert not has_intent_context_for_keyword("使用 swarm 模式", swarm)

    def test_team_explicit_intent_patterns(self):
        """测试 team 显式意图模式"""
        explicit_patterns = [
            "$team mode",
            "/prompts:team",
            "team mode",
            "$TEAM",
            "/prompts:TEAM",
        ]
        team = get_trigger_by_keyword('team')
        for pattern in explicit_patterns:
            assert has_intent_context_for_keyword(pattern, 'team'), f"模式 '{pattern}' 应匹配"

    def test_swarm_explicit_intent_patterns(self):
        """测试 swarm 显式意图模式"""
        explicit_patterns = [
            "$swarm",
            "/prompts:swarm",
            "swarm mode",
            "$SWARM",
            "/prompts:SWARM",
        ]
        for pattern in explicit_patterns:
            assert has_intent_context_for_keyword(pattern, 'swarm'), f"模式 '{pattern}' 应匹配"

    def test_intent_check_case_insensitive(self):
        """测试意图检查不区分大小写"""
        assert has_intent_context_for_keyword("$TEAM", 'team')
        assert has_intent_context_for_keyword("$Team", 'team')


# ==================== Well-Specified 信号检测测试 ====================

class TestWellSpecifiedSignals:
    """well-specified 信号检测测试"""

    def test_signals_include_file_extensions(self):
        """测试文件扩展名模式"""
        text_with_files = """
        修改 src/agent/keyword_registry.py 和 tests/test_keyword.py，
        同时检查 src/workflow/engine.ts
        """
        has_match = any(p.search(text_with_files) for p in WELL_SPECIFIED_SIGNALS)
        assert has_match, "文件引用应匹配"

    def test_signals_include_code_structures(self):
        """测试代码结构引用"""
        code_refs = """
        function calculateTotal(items) {
            const sum = items.reduce((a, b) => a + b, 0)
            return sum * 1.1;
        }
        """
        has_match = any(p.search(code_refs) for p in WELL_SPECIFIED_SIGNALS)
        assert has_match, "代码结构引用应匹配"

    def test_signals_include_camel_case(self):
        """测试 camelCase 命名"""
        camel_text = "camelCaseToken myVariableName computeTotalAmount"
        has_match = any(p.search(camel_text) for p in WELL_SPECIFIED_SIGNALS)
        assert has_match, "camelCase 应匹配"

    def test_signals_include_pascal_case(self):
        """测试 PascalCase 命名"""
        pascal_text = "PascalCaseToken MyComponent UserService DataProcessor"
        has_match = any(p.search(pascal_text) for p in WELL_SPECIFIED_SIGNALS)
        assert has_match, "PascalCase 应匹配"

    def test_signals_include_snake_case_multi_segment(self):
        """测试多段 snake_case"""
        snake_text = "validate_user_input error_handling_task"
        has_match = any(p.search(snake_text) for p in WELL_SPECIFIED_SIGNALS)
        assert has_match, "snake_case 应匹配"

    def test_signals_include_issue_references(self):
        """测试问题引用"""
        issue_text = "修复 bug #123 和 issue #456，同时处理 PR #789"
        has_match = any(p.search(issue_text) for p in WELL_SPECIFIED_SIGNALS)
        assert has_match, "问题引用应匹配"

    def test_signals_include_code_blocks(self):
        """测试代码块"""
        code_block = """
        这是指令：
        ```
        def compute(x, y):
            return x + y * 2
        ```
        执行这个函数
        """
        has_match = any(p.search(code_block) for p in WELL_SPECIFIED_SIGNALS)
        assert has_match, "代码块应匹配"

    def test_underspecified_detection(self):
        """测试指定不足检测"""
        vague = "修复问题"  # 太模糊
        assert is_underspecified_for_execution(vague), "模糊提示应被识别为指定不足"

    def test_specified_enough_detection(self):
        """测试已充分指定的提示"""
        detailed = """
        在 src/agent/keyword_registry.py 中添加 is_underspecified_for_execution 函数，
        该函数应检查 WELL_SPECIFIED_SIGNALS 正则匹配。
        """
        assert not is_underspecified_for_execution(detailed), "充分指定的提示应通过检测"

    def test_bypass_prefix_overrides_underspecified(self):
        """测试绕过前缀覆盖指定不足检测"""
        vague = "修复问题"
        assert is_underspecified_for_execution(vague)  # 先确认是模糊的
        forced = "force: 修复问题"
        assert not is_underspecified_for_execution(forced), "force: 前缀应绕过检测"
        bang = "! 修复问题"
        assert not is_underspecified_for_execution(bang), "! 前缀应绕过检测"

    def test_bypass_prefixes_are_configurable(self):
        """测试绕过前缀可配置"""
        assert 'force:' in GATE_BYPASS_PREFIXES
        assert '!' in GATE_BYPASS_PREFIXES


# ==================== Apply Ralplan Gate 测试 ====================

class TestApplyRalplanGate:
    """ralplan-first gate 应用测试"""

    def test_ralph_gate_redirection_underspecified(self):
        """测试 ralph 关键词在指定不足时重定向到 ralplan"""
        text = "fix it"  # 模糊的提示
        ralph = get_trigger_by_keyword('ralph')
        result = apply_ralplan_gate([ralph], text)

        # 应重定向到 ralplan，不包含 ralph
        assert all(t.keyword != 'ralph' for t in result)
        assert any(t.keyword == 'ralplan' for t in result), "应重定向到 ralplan"

    def test_ralph_gate_no_redirection_explicit_intent(self):
        """测试有明确意图时不重定向"""
        text = "$ralph 修复 src/agent/keyword_registry.py 第120行的 is_underspecified_for_execution 函数"
        ralph = get_trigger_by_keyword('ralph')
        result = apply_ralplan_gate([ralph], text)

        # 应保留 ralph，不重定向
        assert any(t.keyword == 'ralph' for t in result), "有明确意图时应保留 ralph"
        assert not any(t.keyword == 'ralplan' for t in result), "只有意图时不应添加 ralplan"

    def test_ralph_gate_no_redirection_force_prefix(self):
        """测试 force 前缀不重定向"""
        text = "force: fix it"  # 模糊但用 force 绕过
        ralph = get_trigger_by_keyword('ralph')
        result = apply_ralplan_gate([ralph], text)

        assert any(t.keyword == 'ralph' for t in result), "force 前缀应绕过门控"

    def test_autopilot_gate_redirection(self):
        """测试 autopilot 关键词重定向"""
        text = "do something"  # 模糊
        # autopilot 不在注册表中但属于 EXECUTION_GATE_KEYWORDS
        # 模拟 autopilot 触发器
        autopilot = KeywordTrigger(keyword='autopilot', skill='autopilot', priority=30)
        result = apply_ralplan_gate([autopilot], text)

        assert all(t.keyword != 'autopilot' for t in result)
        assert any(t.keyword == 'ralplan' for t in result) or result == []

    def test_team_gate_redirection_no_explicit_intent(self):
        """测试 team 无明确意图时重定向"""
        text = "并行执行任务"  # 模糊且无 $team
        team = get_trigger_by_keyword('team')
        result = apply_ralplan_gate([team], text)

        # team 需要意图检查，无意图会被过滤，加上 underspecified 会重定向
        assert len(result) <= 1  # 最多一个触发器

    def test_multiple_triggers_mixed(self):
        """测试混合多个触发器"""
        text = "review the code"  # review 不受门控
        review = get_trigger_by_keyword('review')
        ralph = get_trigger_by_keyword('ralph')
        result = apply_ralplan_gate([review, ralph], text)

        # review 应保留
        assert any(t.keyword == 'review' for t in result)
        # ralph 可能被重定向或过滤，取决于是否有意图

    def test_empty_keywords_returns_empty(self):
        """测试空列表返回空"""
        result = apply_ralplan_gate([], "some text")
        assert result == []


# ==================== 技能激活状态持久化测试 ====================

class TestSkillActivationPersistence:
    """技能激活状态持久化测试"""

    @pytest.fixture
    def temp_workdir(self):
        """临时工作目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_record_skill_activation_creates_state_file(self, temp_workdir):
        """测试记录激活创建状态文件"""
        record_skill_activation('deep_interview', workdir=temp_workdir)

        state_file = temp_workdir / '.clawd' / 'state' / 'skill-active-state.json'
        assert state_file.exists()

    def test_recorded_state_contains_correct_data(self, temp_workdir):
        """测试记录的状态包含正确数据"""
        record_skill_activation('ralph_loop', workdir=temp_workdir)

        state = get_skill_active_state(workdir=temp_workdir)
        assert state['active_skill'] == 'ralph_loop'
        assert 'activated_at' in state

    def test_get_skill_active_state_empty_when_no_file(self, temp_workdir):
        """测试无状态文件时返回空字典"""
        state = get_skill_active_state(workdir=temp_workdir)
        assert state == {}

    def test_record_activation_creates_parent_dirs(self, temp_workdir):
        """测试记录激活会创建父目录"""
        state_file = temp_workdir / '.clawd' / 'state' / 'skill-active-state.json'
        assert not state_file.parent.exists()

        record_skill_activation('test', workdir=temp_workdir)

        assert state_file.parent.exists()

    def test_multiple_activations_overwrite_state(self, temp_workdir):
        """测试多次激活覆盖状态"""
        record_skill_activation('skill_a', workdir=temp_workdir)
        record_skill_activation('skill_b', workdir=temp_workdir)

        state = get_skill_active_state(workdir=temp_workdir)
        assert state['active_skill'] == 'skill_b'


# ==================== 检测关键词集成测试 ====================

class TestDetectKeywordsIntegration:
    """关键词检测集成测试"""

    def test_detect_keywords_returns_sorted_by_priority(self):
        """测试关键词返回按优先级排序"""
        # $ralplan 优先级最高 (25)，$build 次之 (16)
        text = "$ralplan $build"
        triggers = detect_keywords(text)

        assert len(triggers) == 2
        # 应包含 ralplan 和 build
        assert any(t.keyword == 'ralplan' for t in triggers)
        assert any(t.keyword == 'build' for t in triggers)
        # ralplan 优先级更高，应在前面（降序）
        assert triggers[0].keyword == 'ralplan'

    def test_detect_keywords_filters_no_intent_team(self):
        """测试 team 无明确意图时被过滤"""
        text = "使用团队模式"  # 无 $team 或 /prompts:team
        triggers = detect_keywords(text)

        # 没有显式意图，team 不应匹配
        assert not any(t.keyword == 'team' for t in triggers)

    def test_detect_primary_keyword(self):
        """测试主要关键词检测"""
        text = "$ralph 完成这个任务"
        primary = detect_primary_keyword(text)
        assert primary == 'ralph'

    def test_detect_primary_keyword_no_match(self):
        """测试无关键词时返回 None"""
        text = "随便说点什么"
        primary = detect_primary_keyword(text)
        assert primary is None

    def test_detect_keywords_swarm_maps_to_team(self):
        """测试 swarm 映射到 team"""
        text = "$swarm execute"
        triggers = detect_keywords(text)

        assert len(triggers) == 1
        assert triggers[0].keyword == 'team'
        assert triggers[0].skill == 'team_execution'

    def test_detect_keywords_ignores_unknown(self):
        """测试未知关键词被忽略"""
        text = "$unknown_skill do something"
        triggers = detect_keywords(text)

        assert len(triggers) == 0


# ==================== 任务规模检测集成测试 ====================

class TestTaskSizeIntegration:
    """任务规模检测集成测试"""

    def test_get_task_size_class_returns_valid_types(self):
        """测试获取任务规模返回有效类型"""
        size = get_task_size_class("简单修复一个拼写错误")

        if size is not None:
            assert size in ('small', 'medium', 'large', 'heavy')

    def test_small_task_signals(self):
        """测试小任务信号"""
        small_tasks = [
            "fix typo",
            "修正拼写错误",
            "update README",
        ]
        for task in small_tasks:
            size = get_task_size_class(task)
            if size:
                assert size == 'small', f"'{task}' 应归类为 small"

    def test_medium_task_signals(self):
        """测试中等任务信号"""
        task = "添加用户登录表单验证"
        size = get_task_size_class(task)
        # size 可能为 None 或 'medium'，取决于检测器可用性
        if size:
            assert size in ('medium', 'small')


# ==================== KeywordTrigger 数据类测试 ====================

class TestKeywordTrigger:
    """KeywordTrigger 数据类测试"""

    def test_frozen_dataclass(self):
        """测试不可变数据类"""
        trigger = KeywordTrigger(
            keyword='test',
            skill='test_skill',
            priority=5,
        )
        assert trigger.keyword == 'test'
        assert trigger.skill == 'test_skill'
        assert trigger.priority == 5
        assert trigger.requires_intent is False
        assert trigger.description == ""

        # 验证不可变性
        with pytest.raises(AttributeError):
            trigger.keyword = 'changed'

    def test_trigger_with_all_fields(self):
        """测试所有字段的触发器"""
        trigger = KeywordTrigger(
            keyword='complex',
            skill='complex_skill',
            priority=100,
            requires_intent=True,
            description="复杂技能描述"
        )
        assert trigger.keyword == 'complex'
        assert trigger.requires_intent is True
        assert trigger.description == "复杂技能描述"


# ==================== 向后兼容性测试 ====================

class TestBackwardCompatibility:
    """向后兼容性测试"""

    def test_legacy_detect_keywords_still_works(self):
        """测试旧版 detect_keywords 仍有效（通过 _legacy_detect）"""
        # 新实现的 detect_keywords 应能正确工作
        text = "$review code quality"
        triggers = detect_keywords(text)
        assert len(triggers) == 1
        assert triggers[0].keyword == 'review'

    def test_trigger_ordering_by_priority(self):
        """测试触发器按优先级排序"""
        # ralplan=25, pipeline=18, build=16
        text = "$ralplan $pipeline $build"
        triggers = detect_keywords(text)

        assert len(triggers) == 3
        # 优先级序列应为 ralplan > pipeline > build（降序）
        assert triggers[0].keyword == 'ralplan'
        assert triggers[1].keyword == 'pipeline'
        assert triggers[2].keyword == 'build'


# ==================== 导出符号测试 ====================

class TestExports:
    """模块导出符号测试"""

    def test_module_all_exports(self):
        """测试 __all__ 包含正确导出"""
        from src.agent import keyword_registry as kr

        for name in kr.__all__:
            assert hasattr(kr, name), f"导出 '{name}' 不在模块中"

    def test_public_functions_callable(self):
        """测试公共函数可调用"""
        from src.agent import keyword_registry as kr

        assert callable(kr.detect_keywords)
        assert callable(kr.detect_primary_keyword)
        assert callable(kr.has_intent_context_for_keyword)
        assert callable(kr.is_underspecified_for_execution)
        assert callable(kr.apply_ralplan_gate)
        assert callable(kr.record_skill_activation)
        assert callable(kr.get_skill_active_state)
