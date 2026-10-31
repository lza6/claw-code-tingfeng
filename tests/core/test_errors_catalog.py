"""中文错误字典测试（X-8）

覆盖三件事：
1. **覆盖率**：`ErrorCode` 的每个成员都必须有条目 —— 两条独立断言（`missing_codes()` 与
   逐成员 `lookup()` 反查），避免函数自身有 bug 时假绿；
2. **文案质量**：字段齐全非空、中文说明与下一步（不允许空串或纯英文）、级别在闭集内、
   doc_url 指向排障页；
3. **兜底与稳定性**：未知码不抛异常、`render` 三段齐全、`catalog_entries()` 幂等且返回副本。
"""

from __future__ import annotations

import re

import pytest

from src.core.errors_catalog import (
    CATEGORY_DOCS,
    DOCS_BASE,
    ERRORS_DOC_PATH,
    SEVERITIES,
    catalog_entries,
    coerce,
    doc_url_for,
    lookup,
    missing_codes,
    render,
)
from src.core.exceptions import ClawdError, ErrorCode

CJK = re.compile(r'[一-鿿]')
ENTRY_KEYS = {'code', 'zh_title', 'zh_message', 'next_step', 'doc_url', 'severity'}


# ---------------------------------------------------------------------------
# 覆盖率：不能漏码
# ---------------------------------------------------------------------------


def test_missing_codes_is_empty() -> None:
    """字典必须覆盖全部 ErrorCode 成员。"""
    assert missing_codes() == []


def test_every_enum_member_has_entry_via_lookup() -> None:
    """独立于 missing_codes() 的第二条断言：逐成员反查。"""
    for member in ErrorCode:
        entry = lookup(member)
        assert entry is not None, f'{member.value} 缺少中文条目'
        assert entry['code'] == member.value

    assert len(catalog_entries()) == len(list(ErrorCode))
    assert len(ErrorCode) == 53  # 枚举成员数变动时必须同步审阅字典（本行是护栏）


# ---------------------------------------------------------------------------
# 文案质量
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('entry', catalog_entries(), ids=lambda e: e['code'])
def test_entry_fields_are_complete_and_chinese(entry: dict) -> None:
    """每条条目字段齐全非空，说明/下一步必须是中文（不能空串或纯英文）。"""
    assert set(entry) == ENTRY_KEYS
    for key in ENTRY_KEYS:
        assert isinstance(entry[key], str)
        assert entry[key].strip(), f'{entry["code"]} 的 {key} 为空'

    assert re.fullmatch(r'E\d{4}', entry['code']), f'错误码格式不对: {entry["code"]}'

    for key in ('zh_title', 'zh_message', 'next_step'):
        assert CJK.search(entry[key]), f'{entry["code"]} 的 {key} 不含中文: {entry[key]!r}'
    assert not entry['next_step'].isascii(), f'{entry["code"]} 的 next_step 是纯英文'

    assert entry['severity'] in SEVERITIES
    assert entry['doc_url'].startswith(DOCS_BASE)
    assert ERRORS_DOC_PATH in entry['doc_url']


def test_severity_closed_set() -> None:
    """级别是闭集，避免随手写 'high'/'low' 这种自由文本。"""
    assert set(SEVERITIES) == {'info', 'warning', 'error', 'critical'}
    used = {entry['severity'] for entry in catalog_entries()}
    assert used <= set(SEVERITIES)


def test_doc_url_follows_category_anchor() -> None:
    """doc_url 按码段落到排障页的类别锚点。"""
    assert doc_url_for(ErrorCode.LLM_PROVIDER_NOT_CONFIGURED).endswith(f'{ERRORS_DOC_PATH}#e1xxx-llm')
    assert doc_url_for('E3002').endswith(f'{ERRORS_DOC_PATH}#e3xxx-security')
    assert doc_url_for('E9010').endswith(f'{ERRORS_DOC_PATH}#e9xxx-state')
    # 每个码段都在 CATEGORY_DOCS 里登记，避免出现兜底 anchor 混进正式条目
    for member in ErrorCode:
        assert member.value[:2] in CATEGORY_DOCS


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def test_lookup_accepts_various_forms() -> None:
    """ErrorCode / 码值 / 成员名 / 含码值的整行报错都能查。"""
    assert lookup(ErrorCode.LLM_API_CALL_FAILED)['code'] == 'E1002'
    assert lookup('E1002')['code'] == 'E1002'
    assert lookup('e1002')['code'] == 'E1002'
    assert lookup('LLM_API_CALL_FAILED')['code'] == 'E1002'
    assert lookup('[E1002] LLM API 调用失败')['code'] == 'E1002'


@pytest.mark.parametrize('unknown', ['E9999', '', '  ', '不存在的码', None, 123, object()])
def test_lookup_unknown_returns_none(unknown: object) -> None:
    """未知输入返回 None（不抛异常）。"""
    assert lookup(unknown) is None


# ---------------------------------------------------------------------------
# coerce 兜底
# ---------------------------------------------------------------------------


def test_coerce_from_clawd_error() -> None:
    exc = ClawdError(code=ErrorCode.CONFIG_MISSING, message='缺少必要配置: OPENAI_API_KEY')
    code, entry = coerce(exc)
    assert code == 'E4001'
    assert entry['zh_title']
    assert entry['code'] == 'E4001'


def test_coerce_from_str_and_enum() -> None:
    assert coerce('E3001')[0] == 'E3001'
    assert coerce('E3001')[1]['code'] == 'E3001'
    assert coerce(ErrorCode.TOOL_TIMEOUT)[0] == 'E2003'


def test_coerce_plain_exception_falls_back_to_unknown() -> None:
    """没有错误码的普通异常归入 E0001，而不是当作未登记码。"""
    code, entry = coerce(ValueError('boom'))
    assert code == ErrorCode.UNKNOWN_ERROR.value
    assert entry['code'] == code


def test_coerce_unknown_code_returns_fallback_entry() -> None:
    code, entry = coerce('E9999')
    assert code == 'E9999'
    assert entry['code'] == 'E9999'
    assert entry['zh_title'] == '未登记的错误码'
    assert CJK.search(entry['zh_message'])
    assert CJK.search(entry['next_step'])
    assert entry['severity'] in SEVERITIES


def test_coerce_unknown_string_keeps_raw_text() -> None:
    code, entry = coerce('some-provider-error')
    assert code == 'some-provider-error'
    assert entry['code'] == 'some-provider-error'
    assert '未登记' in entry['zh_title']


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_contains_three_sections() -> None:
    text = render(ErrorCode.API_KEY_INVALID)
    for section in ('问题：', '下一步：', '文档：'):
        assert section in text
    assert 'E7001' in text


def test_render_includes_detail_when_given() -> None:
    text = render('E1001', detail='原始报错：Provider is not configured')
    assert '详情：原始报错：Provider is not configured' in text


def test_render_unknown_code_is_still_readable() -> None:
    """未知码也要给中文说明，不能抛异常或只吐英文。"""
    text = render('E9999')
    assert '未登记的错误码' in text
    for section in ('问题：', '下一步：', '文档：'):
        assert section in text


# ---------------------------------------------------------------------------
# 稳定性
# ---------------------------------------------------------------------------


def test_catalog_entries_idempotent_and_sorted() -> None:
    first = catalog_entries()
    second = catalog_entries()
    assert first == second
    codes = [entry['code'] for entry in first]
    assert codes == sorted(codes)
    assert len(codes) == len(set(codes))


def test_catalog_entries_returns_copies() -> None:
    """外部改动返回值不能污染字典内部状态。"""
    entries = catalog_entries()
    original = dict(entries[0])
    entries[0]['zh_title'] = '被篡改'
    entries.clear()

    fresh = catalog_entries()
    assert fresh[0] == original
    assert all(entry['zh_title'] != '被篡改' for entry in fresh)
    assert lookup(original['code']) == original
