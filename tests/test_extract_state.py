"""Tests for src/riveter/extract_state.py."""

import io
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from riveter.exceptions import FileSystemError, TerraformParsingError
from riveter.extract_state import _build_resource_id, extract_terraform_state

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_state(path: Path, payload: Dict[str, Any]) -> Path:
    """Write a terraform.tfstate JSON file and return its path."""
    state_file = path / "terraform.tfstate"
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    return state_file


def _minimal_state(resources: list | None = None) -> Dict[str, Any]:
    """Return a minimal valid v4 state payload."""
    return {
        "version": 4,
        "terraform_version": "1.5.0",
        "serial": 1,
        "lineage": "abc-123",
        "outputs": {},
        "resources": resources or [],
    }


def _managed_resource(
    resource_type: str = "aws_instance",
    name: str = "web",
    attributes: Dict[str, Any] | None = None,
    module: str | None = None,
    index_key: Any = None,
) -> Dict[str, Any]:
    """Helper to build a single managed resource entry for a state payload."""
    instance: Dict[str, Any] = {"schema_version": 0, "attributes": attributes or {}}
    if index_key is not None:
        instance["index_key"] = index_key
    res: Dict[str, Any] = {
        "mode": "managed",
        "type": resource_type,
        "name": name,
        "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
        "instances": [instance],
    }
    if module:
        res["module"] = module
    return res


# ---------------------------------------------------------------------------
# Basic managed resource
# ---------------------------------------------------------------------------


class TestBasicManagedResource:
    def test_basic_managed_resource(self, tmp_path: Path) -> None:
        attrs = {"instance_type": "t3.large", "associate_public_ip_address": False}
        state_file = _write_state(tmp_path, _minimal_state([_managed_resource(attributes=attrs)]))
        result = extract_terraform_state(str(state_file))

        assert len(result["resources"]) == 1
        r = result["resources"][0]
        assert r["resource_type"] == "aws_instance"
        # id is the bare resource name (no type prefix), matching extract_config.py convention
        assert r["id"] == "web"
        assert r["instance_type"] == "t3.large"
        assert r["associate_public_ip_address"] is False

    def test_resource_type_and_name_in_dict(self, tmp_path: Path) -> None:
        state_file = _write_state(
            tmp_path,
            _minimal_state([_managed_resource(resource_type="aws_s3_bucket", name="my_bucket")]),
        )
        result = extract_terraform_state(str(state_file))
        r = result["resources"][0]
        assert r["resource_type"] == "aws_s3_bucket"
        assert r["id"] == "my_bucket"

    def test_multiple_managed_resources(self, tmp_path: Path) -> None:
        resources = [
            _managed_resource("aws_instance", "web", {"instance_type": "t3.large"}),
            _managed_resource("aws_s3_bucket", "data", {"bucket": "my-data"}),
        ]
        state_file = _write_state(tmp_path, _minimal_state(resources))
        result = extract_terraform_state(str(state_file))

        assert len(result["resources"]) == 2
        types = {r["resource_type"] for r in result["resources"]}
        assert types == {"aws_instance", "aws_s3_bucket"}


# ---------------------------------------------------------------------------
# Data source exclusion
# ---------------------------------------------------------------------------


class TestDataSourceExclusion:
    def test_data_source_excluded(self, tmp_path: Path) -> None:
        data_source = {
            "mode": "data",
            "type": "aws_ami",
            "name": "ubuntu",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [{"schema_version": 0, "attributes": {"id": "ami-12345"}}],
        }
        state_file = _write_state(tmp_path, _minimal_state([data_source]))
        result = extract_terraform_state(str(state_file))
        assert result["resources"] == []

    def test_mixed_modes_only_managed_included(self, tmp_path: Path) -> None:
        data_source = {
            "mode": "data",
            "type": "aws_ami",
            "name": "ubuntu",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [{"schema_version": 0, "attributes": {}}],
        }
        managed = _managed_resource("aws_instance", "web", {"instance_type": "t3.micro"})
        state_file = _write_state(tmp_path, _minimal_state([data_source, managed]))
        result = extract_terraform_state(str(state_file))
        assert len(result["resources"]) == 1
        assert result["resources"][0]["resource_type"] == "aws_instance"


# ---------------------------------------------------------------------------
# count / for_each — multiple instances
# ---------------------------------------------------------------------------


class TestMultipleInstances:
    def test_count_creates_multiple_resources(self, tmp_path: Path) -> None:
        res = {
            "mode": "managed",
            "type": "aws_instance",
            "name": "servers",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [
                {"index_key": 0, "schema_version": 0, "attributes": {"instance_type": "t3.micro"}},
                {"index_key": 1, "schema_version": 0, "attributes": {"instance_type": "t3.large"}},
            ],
        }
        state_file = _write_state(tmp_path, _minimal_state([res]))
        result = extract_terraform_state(str(state_file))

        assert len(result["resources"]) == 2
        ids = {r["id"] for r in result["resources"]}
        assert "servers[0]" in ids
        assert "servers[1]" in ids

    def test_for_each_string_key(self, tmp_path: Path) -> None:
        res = {
            "mode": "managed",
            "type": "aws_instance",
            "name": "env",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [
                {
                    "index_key": "prod",
                    "schema_version": 0,
                    "attributes": {"instance_type": "m5.large"},
                },
                {
                    "index_key": "staging",
                    "schema_version": 0,
                    "attributes": {"instance_type": "t3.micro"},
                },
            ],
        }
        state_file = _write_state(tmp_path, _minimal_state([res]))
        result = extract_terraform_state(str(state_file))

        ids = {r["id"] for r in result["resources"]}
        assert 'env["prod"]' in ids
        assert 'env["staging"]' in ids

    def test_single_instance_no_index_key_no_brackets(self, tmp_path: Path) -> None:
        state_file = _write_state(tmp_path, _minimal_state([_managed_resource()]))
        result = extract_terraform_state(str(state_file))
        # No index_key → id is just the bare name, no brackets
        assert result["resources"][0]["id"] == "web"


# ---------------------------------------------------------------------------
# Module resources
# ---------------------------------------------------------------------------


class TestModuleResources:
    def test_module_prefix_in_id(self, tmp_path: Path) -> None:
        state_file = _write_state(
            tmp_path,
            _minimal_state([_managed_resource(module="module.vpc")]),
        )
        result = extract_terraform_state(str(state_file))
        # Module path prefixes the name, but resource type is NOT included in id
        assert result["resources"][0]["id"] == "module.vpc.web"

    def test_module_with_index_key(self, tmp_path: Path) -> None:
        res = {
            "module": "module.app",
            "mode": "managed",
            "type": "aws_instance",
            "name": "api",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [
                {"index_key": 0, "schema_version": 0, "attributes": {}},
            ],
        }
        state_file = _write_state(tmp_path, _minimal_state([res]))
        result = extract_terraform_state(str(state_file))
        assert result["resources"][0]["id"] == "module.app.api[0]"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileSystemError, match="not found"):
            extract_terraform_state(str(tmp_path / "nonexistent.tfstate"))

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "terraform.tfstate"
        bad_file.write_text("{ not valid json }", encoding="utf-8")
        with pytest.raises(TerraformParsingError, match="Failed to parse state JSON"):
            extract_terraform_state(str(bad_file))

    def test_missing_version_key_raises(self, tmp_path: Path) -> None:
        state_file = tmp_path / "terraform.tfstate"
        state_file.write_text(json.dumps({"resources": []}), encoding="utf-8")
        with pytest.raises(TerraformParsingError, match="missing 'version'"):
            extract_terraform_state(str(state_file))

    def test_state_version_3_raises(self, tmp_path: Path) -> None:
        state_file = _write_state(tmp_path, {"version": 3, "resources": []})
        with pytest.raises(TerraformParsingError, match="version 3 is not supported"):
            extract_terraform_state(str(state_file))

    def test_state_version_1_raises(self, tmp_path: Path) -> None:
        state_file = _write_state(tmp_path, {"version": 1, "modules": []})
        with pytest.raises(TerraformParsingError):
            extract_terraform_state(str(state_file))

    def test_file_too_large_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import riveter.extract_state as es_module

        state_file = _write_state(tmp_path, _minimal_state())
        # Drive the size-check to fail by making the limit -1 (any file exceeds it)
        monkeypatch.setattr(es_module, "_MAX_STATE_SIZE", -1)
        with pytest.raises(FileSystemError, match="50 MB"):
            extract_terraform_state(str(state_file))

    def test_empty_resources_list(self, tmp_path: Path) -> None:
        state_file = _write_state(tmp_path, _minimal_state([]))
        result = extract_terraform_state(str(state_file))
        assert result == {"resources": []}

    def test_no_resources_key(self, tmp_path: Path) -> None:
        state_file = _write_state(tmp_path, {"version": 4, "serial": 1})
        result = extract_terraform_state(str(state_file))
        assert result == {"resources": []}


# ---------------------------------------------------------------------------
# Stdin support
# ---------------------------------------------------------------------------


class TestStdinSupport:
    def test_stdin_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attrs = {"instance_type": "t3.large"}
        payload = _minimal_state([_managed_resource(attributes=attrs)])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

        result = extract_terraform_state("-")
        assert len(result["resources"]) == 1
        assert result["resources"][0]["instance_type"] == "t3.large"

    def test_stdin_invalid_json_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        with pytest.raises(TerraformParsingError):
            extract_terraform_state("-")


# ---------------------------------------------------------------------------
# _build_resource_id unit tests
# ---------------------------------------------------------------------------


class TestBuildResourceId:
    def test_simple(self) -> None:
        # resource_type is NOT included in the id (matches extract_config.py convention)
        assert _build_resource_id("aws_instance", "web", None, None) == "web"

    def test_with_module(self) -> None:
        assert _build_resource_id("aws_instance", "web", "module.vpc", None) == "module.vpc.web"

    def test_with_integer_index(self) -> None:
        assert _build_resource_id("aws_instance", "web", None, 0) == "web[0]"

    def test_with_string_index(self) -> None:
        assert _build_resource_id("aws_instance", "web", None, "prod") == 'web["prod"]'

    def test_with_module_and_index(self) -> None:
        assert _build_resource_id("aws_instance", "web", "module.app", 2) == "module.app.web[2]"
