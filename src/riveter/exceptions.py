"""Custom exception hierarchy for Riveter."""

from typing import Any, Dict, List, Optional


class RiveterError(Exception):
    """Base exception for all Riveter errors."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        suggestions: Optional[List[str]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.suggestions = suggestions or []

    def __str__(self) -> str:
        result = self.message
        if self.suggestions:
            result += "\nSuggestions:"
            for s in self.suggestions:
                result += f"\n  - {s}"
        return result


class ConfigurationError(RiveterError):
    """Raised when configuration is invalid."""

    def __init__(self, message: str, config_file: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        if config_file:
            self.details["config_file"] = config_file


class TerraformParsingError(RiveterError):
    """Raised when a Terraform file cannot be parsed."""

    def __init__(
        self,
        message: str,
        terraform_file: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        if terraform_file:
            self.details["terraform_file"] = terraform_file
        if not self.suggestions:
            self.suggestions = [
                "Check for syntax errors in the Terraform file",
                "Ensure all brackets and quotes are properly closed",
                "Verify that the file is valid HCL format",
                "Try running 'terraform validate' on the file",
            ]


class RuleValidationError(RiveterError):
    """Raised when a rule definition is invalid."""

    def __init__(
        self,
        message: str,
        rule_id: Optional[str] = None,
        rule_file: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        if rule_id:
            self.details["rule_id"] = rule_id
        if rule_file:
            self.details["rule_file"] = rule_file


class RulePackError(RiveterError):
    """Raised when a rule pack cannot be loaded or is invalid."""

    def __init__(self, message: str, pack_name: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        if pack_name:
            self.details["pack_name"] = pack_name


class FileSystemError(RiveterError):
    """Raised when a file system operation fails."""

    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        if file_path:
            self.details["file_path"] = file_path
        if not self.suggestions:
            self.suggestions = [
                "Check that the file or directory exists",
                "Verify that you have the necessary permissions",
                "Ensure the path is correct and accessible",
            ]
