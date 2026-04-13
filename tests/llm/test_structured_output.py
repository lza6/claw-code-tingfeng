"""Structured output tests - 覆盖 _parse_json_response、schema 验证等"""
import pytest
from src.llm.structured_output import (
    StructuredOutputMixin,
    JsonSchema,
    StructuredResponse,
)
from src.llm import LLMResponse


class ExtractorTestMixin(StructuredOutputMixin):
    """Concrete test mixin that doesn't need real LLM calls"""
    pass


class TestJsonSchema:
    def test_validate_required_fields(self):
        schema = JsonSchema(
            type="object",
            properties={"name": {"type": "string"}, "age": {"type": "integer"}},
            required=["name"],
        )
        valid, err = schema.validate({"name": "Alice"})
        assert valid is True

        valid, err = schema.validate({})
        assert valid is False
        assert "name" in err

    def test_validate_type_mismatch(self):
        schema = JsonSchema(
            type="object",
            properties={"count": {"type": "integer"}},
            required=["count"],
        )
        valid, err = schema.validate({"count": "not_a_number"})
        assert valid is False

    def test_validate_extra_fields_disallowed(self):
        schema = JsonSchema(
            type="object",
            properties={"name": {"type": "string"}},
            required=["name"],
            additional_properties=False,
        )
        valid, err = schema.validate({"name": "Alice", "extra": "field"})
        assert valid is False
        assert "extra" in err

    def test_validate_extra_fields_allowed(self):
        schema = JsonSchema(
            type="object",
            properties={"name": {"type": "string"}},
            additional_properties=True,
        )
        valid, err = schema.validate({"name": "Alice", "extra": "field"})
        assert valid is True

    def test_from_dict(self):
        d = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        schema = JsonSchema.from_dict(d)
        assert schema.type == "object"
        assert "x" in schema.properties
        assert "x" in schema.required

    def test_to_dict(self):
        schema = JsonSchema(type="object", properties={"a": {"type": "string"}}, required=["a"])
        d = schema.to_dict()
        assert d["type"] == "object"
        assert d["required"] == ["a"]

    def test_validate_non_object_type(self):
        schema = JsonSchema(type="string")
        valid, err = schema.validate({"anything": "value"})
        assert valid is True  # Non-object types skip validation


class TestStructuredResponse:
    def test_is_valid_property(self):
        resp = StructuredResponse(data={"x": 1}, raw_content="{}", success=True)
        assert resp.is_valid is True

    def test_is_valid_with_validation_error(self):
        resp = StructuredResponse(
            data={"x": 1}, raw_content="{}", success=True, validation_error="type mismatch",
        )
        assert resp.is_valid is False

    def test_is_valid_when_not_success(self):
        resp = StructuredResponse(data={}, raw_content="", success=False, error="parse error")
        assert resp.is_valid is False

    def test_get_typed(self):
        resp = StructuredResponse(data={"name": "test"}, raw_content="", success=True)
        assert resp.get_typed("name") == "test"
        assert resp.get_typed("missing", "default") == "default"
        assert resp.get_typed("missing") is None

    def test_get_typed_when_not_success(self):
        resp = StructuredResponse(data={}, raw_content="", success=False)
        assert resp.get_typed("x", 42) == 42


class TestJsonExtraction:
    def test_extract_json_object(self):
        result = ExtractorTestMixin._extract_json('Here is the data: {"key": "value"} end.')
        assert result == '{"key": "value"}'

    def test_extract_json_no_surrounding_text(self):
        result = ExtractorTestMixin._extract_json('{"a": 1, "b": 2}')
        assert result == '{"a": 1, "b": 2}'

    def test_extract_json_array(self):
        result = ExtractorTestMixin._extract_json('data: [1, 2, 3]')
        assert result == '[1, 2, 3]'

    def test_extract_json_nested(self):
        result = ExtractorTestMixin._extract_json('{"outer": {"inner": {"deep": true}}}')
        assert result == '{"outer": {"inner": {"deep": true}}}'

    def test_no_json_found(self):
        result = ExtractorTestMixin._extract_json("no json here at all")
        assert result is None

    def test_strip_markdown_code_block(self):
        content = '```json\n{"key": "value"}\n```'
        mixin = ExtractorTestMixin()
        result = mixin._strip_markdown_code_blocks(content)
        assert result == '{"key": "value"}'

    def test_strip_markdown_code_block_no_lang(self):
        content = '```\n{"key": "value"}\n```'
        mixin = ExtractorTestMixin()
        result = mixin._strip_markdown_code_blocks(content)
        assert result == '{"key": "value"}'

    def test_parse_json_from_clean_json(self):
        resp = LLMResponse(content='{"key": "value"}', model="test")
        mixin = ExtractorTestMixin()
        result = mixin._parse_json_response(resp)
        assert result.success is True
        assert result.data == {"key": "value"}

    def test_parse_json_from_markdown(self):
        resp = LLMResponse(content='```json\n{"key": "value"}\n```', model="test")
        mixin = ExtractorTestMixin()
        result = mixin._parse_json_response(resp)
        assert result.success is True
        assert result.data == {"key": "value"}

    def test_parse_json_invalid(self):
        resp = LLMResponse(content="not valid json at all", model="test")
        mixin = ExtractorTestMixin()
        result = mixin._parse_json_response(resp)
        assert result.success is False
        assert result.error

    def test_extract_manual_json(self):
        # Fallback manual extraction
        result = ExtractorTestMixin._extract_json_manual('prefix {"a": 1} suffix')
        assert result == '{"a": 1}'

    def test_is_balanced_json_valid(self):
        assert ExtractorTestMixin._is_balanced_json('{"a": 1}')
        assert ExtractorTestMixin._is_balanced_json('[1, 2, 3]')

    def test_is_balanced_json_invalid(self):
        assert not ExtractorTestMixin._is_balanced_json('{"a": ')
        assert not ExtractorTestMixin._is_balanced_json('not json')


class TestConstraintMessage:
    """Test the build_constraint_message helper"""
    def test_build_constraint_message(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        constraint = ExtractorTestMixin._build_constraint_message(schema)
        assert "JSON" in constraint
        assert "name" in constraint
