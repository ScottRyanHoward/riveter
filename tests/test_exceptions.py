"""Tests for the custom exception hierarchy in riveter.exceptions."""

import pytest

from riveter.exceptions import (
    ConfigurationError,
    FileSystemError,
    RiveterError,
    RulePackError,
    RuleValidationError,
    TerraformParsingError,
)


# ---------------------------------------------------------------------------
# RiveterError base class
# ---------------------------------------------------------------------------


class TestRiveterError:
    def test_basic_message(self):
        exc = RiveterError("Something went wrong")
        assert str(exc) == "Something went wrong"
        assert exc.message == "Something went wrong"

    def test_details_stored(self):
        exc = RiveterError("Error", details={"file": "main.tf", "line": 10})
        assert exc.details == {"file": "main.tf", "line": 10}

    def test_details_defaults_to_empty_dict(self):
        exc = RiveterError("Error")
        assert exc.details == {}

    def test_suggestions_stored(self):
        suggestions = ["Check config", "Try again"]
        exc = RiveterError("Error", suggestions=suggestions)
        assert exc.suggestions == suggestions

    def test_suggestions_defaults_to_empty_list(self):
        exc = RiveterError("Error")
        assert exc.suggestions == []

    def test_str_with_suggestions(self):
        exc = RiveterError("Error occurred", suggestions=["Do this", "Try that"])
        result = str(exc)
        assert "Error occurred" in result
        assert "Do this" in result
        assert "Try that" in result

    def test_str_without_suggestions(self):
        exc = RiveterError("Simple error")
        assert str(exc) == "Simple error"
        assert "Suggestions" not in str(exc)

    def test_is_exception_subclass(self):
        exc = RiveterError("msg")
        assert isinstance(exc, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(RiveterError, match="Test error"):
            raise RiveterError("Test error")


# ---------------------------------------------------------------------------
# ConfigurationError
# ---------------------------------------------------------------------------


class TestConfigurationError:
    def test_basic(self):
        exc = ConfigurationError("Invalid config")
        assert "Invalid config" in str(exc)

    def test_config_file_stored_in_details(self):
        exc = ConfigurationError("Bad config", config_file="/path/to/riveter.yml")
        assert exc.details["config_file"] == "/path/to/riveter.yml"

    def test_no_config_file_does_not_set_detail(self):
        exc = ConfigurationError("Bad config")
        assert "config_file" not in exc.details

    def test_is_riveter_error(self):
        exc = ConfigurationError("Error")
        assert isinstance(exc, RiveterError)

    def test_suggestions_can_be_passed(self):
        exc = ConfigurationError("Error", suggestions=["Fix it"])
        assert "Fix it" in exc.suggestions


# ---------------------------------------------------------------------------
# TerraformParsingError
# ---------------------------------------------------------------------------


class TestTerraformParsingError:
    def test_basic(self):
        exc = TerraformParsingError("Parse failed")
        assert "Parse failed" in str(exc)

    def test_terraform_file_stored_in_details(self):
        exc = TerraformParsingError("Parse failed", terraform_file="main.tf")
        assert exc.details["terraform_file"] == "main.tf"

    def test_no_terraform_file_does_not_set_detail(self):
        exc = TerraformParsingError("Parse failed")
        assert "terraform_file" not in exc.details

    def test_auto_populates_suggestions(self):
        exc = TerraformParsingError("Parse failed")
        assert len(exc.suggestions) > 0
        # Should mention syntax or HCL
        suggestions_text = " ".join(exc.suggestions).lower()
        assert "syntax" in suggestions_text or "hcl" in suggestions_text

    def test_custom_suggestions_override_auto(self):
        exc = TerraformParsingError("Parse failed", suggestions=["My suggestion"])
        assert exc.suggestions == ["My suggestion"]

    def test_is_riveter_error(self):
        exc = TerraformParsingError("Error")
        assert isinstance(exc, RiveterError)


# ---------------------------------------------------------------------------
# RuleValidationError
# ---------------------------------------------------------------------------


class TestRuleValidationError:
    def test_basic(self):
        exc = RuleValidationError("Invalid rule")
        assert "Invalid rule" in str(exc)

    def test_rule_id_stored_in_details(self):
        exc = RuleValidationError("Bad rule", rule_id="ec2-check-type")
        assert exc.details["rule_id"] == "ec2-check-type"

    def test_rule_file_stored_in_details(self):
        exc = RuleValidationError("Bad rule", rule_file="rules.yml")
        assert exc.details["rule_file"] == "rules.yml"

    def test_both_rule_id_and_file(self):
        exc = RuleValidationError("Bad", rule_id="my-rule", rule_file="rules.yml")
        assert exc.details["rule_id"] == "my-rule"
        assert exc.details["rule_file"] == "rules.yml"

    def test_no_optional_args_empty_details(self):
        exc = RuleValidationError("Error")
        assert "rule_id" not in exc.details
        assert "rule_file" not in exc.details

    def test_is_riveter_error(self):
        exc = RuleValidationError("Error")
        assert isinstance(exc, RiveterError)


# ---------------------------------------------------------------------------
# RulePackError
# ---------------------------------------------------------------------------


class TestRulePackError:
    def test_basic(self):
        exc = RulePackError("Pack not found")
        assert "Pack not found" in str(exc)

    def test_pack_name_stored_in_details(self):
        exc = RulePackError("Pack missing", pack_name="aws-security")
        assert exc.details["pack_name"] == "aws-security"

    def test_no_pack_name_does_not_set_detail(self):
        exc = RulePackError("Error")
        assert "pack_name" not in exc.details

    def test_is_riveter_error(self):
        exc = RulePackError("Error")
        assert isinstance(exc, RiveterError)


# ---------------------------------------------------------------------------
# FileSystemError
# ---------------------------------------------------------------------------


class TestFileSystemError:
    def test_basic(self):
        exc = FileSystemError("File not found")
        assert "File not found" in str(exc)

    def test_file_path_stored_in_details(self):
        exc = FileSystemError("Not found", file_path="/some/path/file.tf")
        assert exc.details["file_path"] == "/some/path/file.tf"

    def test_no_file_path_does_not_set_detail(self):
        exc = FileSystemError("Error")
        assert "file_path" not in exc.details

    def test_auto_populates_suggestions(self):
        exc = FileSystemError("Not found")
        assert len(exc.suggestions) > 0
        suggestions_text = " ".join(exc.suggestions).lower()
        assert "exist" in suggestions_text or "permission" in suggestions_text or "path" in suggestions_text

    def test_custom_suggestions_override_auto(self):
        exc = FileSystemError("Error", suggestions=["Custom suggestion"])
        assert exc.suggestions == ["Custom suggestion"]

    def test_is_riveter_error(self):
        exc = FileSystemError("Error")
        assert isinstance(exc, RiveterError)
