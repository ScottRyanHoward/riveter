"""Tests for comparison operators."""

import pytest

from riveter.operators import (
    AttributeResolutionError,
    ListOperator,
    NestedAttributeResolver,
    NumericOperator,
    OperatorFactory,
    RegexOperator,
)


class TestNumericOperator:
    def test_eq_passes(self):
        assert NumericOperator("eq").evaluate(5, 5) is True

    def test_eq_fails(self):
        assert NumericOperator("eq").evaluate(5, 6) is False

    def test_ne(self):
        assert NumericOperator("ne").evaluate(5, 6) is True
        assert NumericOperator("ne").evaluate(5, 5) is False

    def test_gt(self):
        assert NumericOperator("gt").evaluate(10, 5) is True
        assert NumericOperator("gt").evaluate(5, 10) is False

    def test_gte(self):
        assert NumericOperator("gte").evaluate(5, 5) is True
        assert NumericOperator("gte").evaluate(6, 5) is True
        assert NumericOperator("gte").evaluate(4, 5) is False

    def test_lt(self):
        assert NumericOperator("lt").evaluate(3, 5) is True
        assert NumericOperator("lt").evaluate(5, 3) is False

    def test_lte(self):
        assert NumericOperator("lte").evaluate(5, 5) is True
        assert NumericOperator("lte").evaluate(4, 5) is True
        assert NumericOperator("lte").evaluate(6, 5) is False

    def test_none_actual_returns_false(self):
        assert NumericOperator("eq").evaluate(None, 5) is False

    def test_string_numbers(self):
        assert NumericOperator("gte").evaluate("100", 50) is True

    def test_invalid_operator_raises(self):
        with pytest.raises(ValueError, match="Invalid numeric operator"):
            NumericOperator("invalid")

    def test_error_message(self):
        msg = NumericOperator("gt").get_error_message(3, 10)
        assert "3" in msg and "10" in msg


class TestRegexOperator:
    def test_match_passes(self):
        assert RegexOperator().evaluate("t3.large", r"^t3\.(large|xlarge)$") is True

    def test_no_match_fails(self):
        assert RegexOperator().evaluate("t2.micro", r"^t3\.(large|xlarge)$") is False

    def test_none_actual_returns_false(self):
        assert RegexOperator().evaluate(None, r".*") is False

    def test_invalid_pattern_returns_false(self):
        assert RegexOperator().evaluate("hello", r"[invalid") is False

    def test_error_message(self):
        msg = RegexOperator().get_error_message("foo", r"^bar$")
        assert "foo" in msg and "bar" in msg


class TestListOperator:
    def test_contains_passes(self):
        assert ListOperator("contains").evaluate([1, 2, 3], 2) is True

    def test_contains_fails(self):
        assert ListOperator("contains").evaluate([1, 2, 3], 5) is False

    def test_contains_non_list_fails(self):
        assert ListOperator("contains").evaluate("not a list", "x") is False

    def test_length_exact(self):
        assert ListOperator("length").evaluate([1, 2, 3], 3) is True
        assert ListOperator("length").evaluate([1, 2], 3) is False

    def test_length_dict_operators(self):
        assert ListOperator("length").evaluate([1, 2, 3, 4, 5], {"lte": 10}) is True
        assert ListOperator("length").evaluate([1, 2, 3, 4, 5], {"gte": 3, "lte": 10}) is True
        assert ListOperator("length").evaluate([1, 2], {"gte": 5}) is False

    def test_subset_passes(self):
        assert ListOperator("subset").evaluate([1, 2, 3, 4], [2, 3]) is True

    def test_subset_fails(self):
        assert ListOperator("subset").evaluate([1, 2], [3, 4]) is False

    def test_invalid_operation_raises(self):
        with pytest.raises(ValueError, match="Invalid list operation"):
            ListOperator("unknown")

    def test_error_message_contains(self):
        msg = ListOperator("contains").get_error_message([1, 2], 99)
        assert "99" in msg


class TestOperatorFactory:
    def test_creates_numeric(self):
        op = OperatorFactory.create_operator("gt")
        assert isinstance(op, NumericOperator)

    def test_creates_regex(self):
        op = OperatorFactory.create_operator("regex")
        assert isinstance(op, RegexOperator)

    def test_creates_list(self):
        op = OperatorFactory.create_operator("contains")
        assert isinstance(op, ListOperator)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            OperatorFactory.create_operator("unknown_op")

    def test_dict_input(self):
        op = OperatorFactory.create_operator({"gte": 5})
        assert isinstance(op, NumericOperator)


class TestNestedAttributeResolver:
    def setup_method(self):
        self.resolver = NestedAttributeResolver()

    def test_simple_key(self):
        assert self.resolver.resolve_path({"foo": "bar"}, "foo") == "bar"

    def test_nested_dot_notation(self):
        obj = {"root_block_device": {"encrypted": True}}
        assert self.resolver.resolve_path(obj, "root_block_device.encrypted") is True

    def test_missing_key_returns_none(self):
        assert self.resolver.resolve_path({"a": 1}, "b") is None

    def test_array_index(self):
        obj = {"security_groups": ["sg-1", "sg-2", "sg-3"]}
        assert self.resolver.resolve_path(obj, "security_groups[1]") == "sg-2"

    def test_nested_array(self):
        obj = {"ingress": [{"port": 80}, {"port": 443}]}
        assert self.resolver.resolve_path(obj, "ingress[0].port") == 80

    def test_path_exists_true(self):
        assert self.resolver.path_exists({"a": {"b": True}}, "a.b") is True

    def test_path_exists_false(self):
        assert self.resolver.path_exists({"a": {}}, "a.missing") is False

    def test_empty_path_returns_whole_object(self):
        obj = {"x": 1}
        assert self.resolver.resolve_path(obj, "") == obj

    def test_depth_limit_raises(self):
        # Build a deeply nested path beyond the 20-segment limit
        deep_path = ".".join(["a"] * 25)
        with pytest.raises(AttributeResolutionError):
            self.resolver.resolve_path({}, deep_path)

    def test_integer_index_out_of_bounds_returns_none(self):
        obj = {"items": ["a", "b"]}
        result = self.resolver.resolve_path(obj, "items[5]")
        assert result is None

    def test_nested_missing_intermediate_returns_none(self):
        obj = {"a": {"b": 1}}
        assert self.resolver.resolve_path(obj, "a.c.d") is None


class TestNumericOperatorEdgeCases:
    def test_non_numeric_string_returns_false(self):
        # "t3.large" cannot be cast to float → should return False, not raise
        assert NumericOperator("gt").evaluate("t3.large", 5) is False

    def test_none_expected_returns_false(self):
        # float(None) raises TypeError → should return False
        assert NumericOperator("eq").evaluate(5, None) is False

    def test_integer_actual_float_expected(self):
        assert NumericOperator("eq").evaluate(10, 10.0) is True

    def test_ne_with_equal_values_returns_false(self):
        assert NumericOperator("ne").evaluate(42, 42) is False


class TestListOperatorEdgeCases:
    def test_contains_with_none_actual_returns_false(self):
        assert ListOperator("contains").evaluate(None, "x") is False

    def test_subset_with_none_actual_returns_false(self):
        assert ListOperator("subset").evaluate(None, ["x"]) is False

    def test_length_with_none_actual_returns_false(self):
        assert ListOperator("length").evaluate(None, 3) is False

    def test_length_with_string_non_list_returns_false(self):
        assert ListOperator("length").evaluate("not-a-list", 3) is False


class TestOperatorFactoryEdgeCases:
    def test_dict_operator_with_multiple_keys(self):
        # e.g. {"gte": 3, "lte": 10} → NumericOperator for first key
        op = OperatorFactory.create_operator({"gte": 3, "lte": 10})
        assert isinstance(op, NumericOperator)
