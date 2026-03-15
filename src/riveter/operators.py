"""Comparison operators for rule assertion evaluation."""

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Union


class ComparisonOperator(ABC):
    """Base class for all comparison operators."""

    @abstractmethod
    def evaluate(self, actual: Any, expected: Any) -> bool:
        """Evaluate the comparison. Returns True if the assertion passes."""

    @abstractmethod
    def get_error_message(self, actual: Any, expected: Any) -> str:
        """Return a human-readable description of the failure."""


class NumericOperator(ComparisonOperator):
    """Handles numeric comparisons: eq, ne, gt, gte, lt, lte."""

    _SYMBOLS = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<=", "ne": "!=", "eq": "=="}

    def __init__(self, operator: str) -> None:
        if operator not in self._SYMBOLS:
            raise ValueError(f"Invalid numeric operator: {operator}")
        self.operator = operator

    def evaluate(self, actual: Any, expected: Any) -> bool:
        try:
            a = float(actual) if actual is not None else None
            e = float(expected)
            if a is None:
                return False
            ops = {
                "gt": lambda x, y: x > y,
                "lt": lambda x, y: x < y,
                "gte": lambda x, y: x >= y,
                "lte": lambda x, y: x <= y,
                "ne": lambda x, y: x != y,
                "eq": lambda x, y: x == y,
            }
            return ops[self.operator](a, e)
        except (ValueError, TypeError):
            return False

    def get_error_message(self, actual: Any, expected: Any) -> str:
        sym = self._SYMBOLS[self.operator]
        return f"Expected value {actual!r} {sym} {expected}, but condition failed"


class RegexOperator(ComparisonOperator):
    """Handles regular expression pattern matching."""

    def evaluate(self, actual: Any, expected: Any) -> bool:
        if actual is None:
            return False
        try:
            return bool(re.match(str(expected), str(actual)))
        except re.error:
            return False

    def get_error_message(self, actual: Any, expected: Any) -> str:
        return f"Value {actual!r} does not match pattern {expected!r}"


class ListOperator(ComparisonOperator):
    """Handles list-based operations: contains, length, subset."""

    def __init__(self, operation: str) -> None:
        if operation not in ("contains", "length", "subset"):
            raise ValueError(f"Invalid list operation: {operation}")
        self.operation = operation

    def evaluate(self, actual: Any, expected: Any) -> bool:
        if self.operation == "contains":
            return isinstance(actual, (list, tuple)) and expected in actual
        if self.operation == "length":
            if not isinstance(actual, (list, tuple, str)):
                return False
            length = len(actual)
            if isinstance(expected, int):
                return length == expected
            if isinstance(expected, dict):
                return all(NumericOperator(op).evaluate(length, val) for op, val in expected.items())
            return False
        if self.operation == "subset":
            if not isinstance(actual, (list, tuple)) or not isinstance(expected, (list, tuple)):
                return False
            try:
                return set(expected).issubset(set(actual))
            except TypeError:
                return all(item in actual for item in expected)
        return False

    def get_error_message(self, actual: Any, expected: Any) -> str:
        if self.operation == "contains":
            return f"List {actual} does not contain {expected!r}"
        if self.operation == "length":
            length = len(actual) if isinstance(actual, (list, tuple, str)) else "N/A"
            return f"Length {length} does not satisfy {expected}"
        return f"Expected subset {expected} is not contained in {actual}"


class OperatorFactory:
    """Creates the appropriate operator from a name or config dict."""

    _NUMERIC = {"gt", "lt", "gte", "lte", "ne", "eq"}
    _LIST = {"contains", "length", "subset"}

    @staticmethod
    def create_operator(operator_config: Union[str, Dict[str, Any]]) -> ComparisonOperator:
        name = operator_config if isinstance(operator_config, str) else next(iter(operator_config))
        if name in OperatorFactory._NUMERIC:
            return NumericOperator(name)
        if name == "regex":
            return RegexOperator()
        if name in OperatorFactory._LIST:
            return ListOperator(name)
        raise ValueError(f"Unknown operator: {name!r}")


_MAX_PATH_DEPTH = 20


class NestedAttributeResolver:
    """Resolves dot-notation and bracket-notation attribute paths in nested dicts."""

    def resolve_path(self, obj: Dict[str, Any], path: str) -> Any:
        """Traverse obj using path (e.g. 'root_block_device.encrypted' or 'tags[0].Name').

        Returns the value at the path, or None if any segment is missing.
        Raises AttributeResolutionError if the path is malformed or too deep.
        """
        if not path:
            return obj
        parts = self._parse_path(path)
        if len(parts) > _MAX_PATH_DEPTH:
            raise AttributeResolutionError(
                f"Path depth {len(parts)} exceeds maximum of {_MAX_PATH_DEPTH}: {path}"
            )
        current: Any = obj
        for part in parts:
            if current is None:
                return None
            if isinstance(part, int):
                if isinstance(current, (list, tuple)) and 0 <= part < len(current):
                    current = current[part]
                else:
                    return None
            else:
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None
        return current

    def path_exists(self, obj: Dict[str, Any], path: str) -> bool:
        """Returns True if the path resolves to a non-None value."""
        try:
            return self.resolve_path(obj, path) is not None
        except AttributeResolutionError:
            return False

    def _parse_path(self, path: str) -> List[Union[str, int]]:
        parts: List[Union[str, int]] = []
        current = ""
        i = 0
        while i < len(path):
            ch = path[i]
            if ch == ".":
                if current:
                    parts.append(current)
                    current = ""
            elif ch == "[":
                if current:
                    parts.append(current)
                    current = ""
                j = path.index("]", i + 1)
                try:
                    parts.append(int(path[i + 1 : j]))
                except ValueError as exc:
                    raise AttributeResolutionError(
                        f"Invalid array index in path: {path}"
                    ) from exc
                i = j
            else:
                current += ch
            i += 1
        if current:
            parts.append(current)
        return parts


class AttributeResolutionError(Exception):
    """Raised when a dot-notation path cannot be resolved."""
