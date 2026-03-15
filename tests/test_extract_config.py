"""Tests for Terraform HCL extraction."""

from pathlib import Path

import pytest

from riveter.exceptions import FileSystemError, TerraformParsingError
from riveter.extract_config import _build_resource, extract_terraform_config


_SIMPLE_TF = """\
resource "aws_instance" "web" {
  instance_type = "t3.micro"
  ami           = "ami-12345678"
}
"""

_MULTI_TF = """\
resource "aws_s3_bucket" "my_bucket" {
  bucket = "my-bucket"
}

resource "aws_iam_role" "my_role" {
  name = "my-role"
}
"""

_NO_RESOURCE_TF = """\
terraform {
  required_version = ">= 1.0"
}
"""

_EMPTY_TF = ""


class TestExtractTerraformConfig:
    def test_single_file_basic(self, tmp_path):
        tf = tmp_path / "main.tf"
        tf.write_text(_SIMPLE_TF)
        result = extract_terraform_config(str(tf))
        assert "resources" in result
        resources = result["resources"]
        assert len(resources) == 1
        r = resources[0]
        assert r["resource_type"] == "aws_instance"
        assert r["id"] == "web"
        assert r["instance_type"] == "t3.micro"

    def test_multiple_resources(self, tmp_path):
        tf = tmp_path / "main.tf"
        tf.write_text(_MULTI_TF)
        result = extract_terraform_config(str(tf))
        types = {r["resource_type"] for r in result["resources"]}
        assert "aws_s3_bucket" in types
        assert "aws_iam_role" in types

    def test_no_resource_blocks(self, tmp_path):
        tf = tmp_path / "provider.tf"
        tf.write_text(_NO_RESOURCE_TF)
        result = extract_terraform_config(str(tf))
        assert result["resources"] == []

    def test_empty_file(self, tmp_path):
        tf = tmp_path / "empty.tf"
        tf.write_text(_EMPTY_TF)
        result = extract_terraform_config(str(tf))
        assert result["resources"] == []

    def test_directory_with_tf_files(self, tmp_path):
        (tmp_path / "a.tf").write_text(_SIMPLE_TF)
        (tmp_path / "b.tf").write_text(_MULTI_TF)
        result = extract_terraform_config(str(tmp_path))
        assert len(result["resources"]) == 3

    def test_directory_no_tf_files(self, tmp_path):
        result = extract_terraform_config(str(tmp_path))
        assert result["resources"] == []

    def test_path_not_found_raises(self):
        with pytest.raises(FileSystemError, match="not found"):
            extract_terraform_config("/nonexistent/path/main.tf")

    def test_invalid_hcl_raises(self, tmp_path):
        tf = tmp_path / "bad.tf"
        tf.write_text("this is not valid hcl {\n")
        with pytest.raises(TerraformParsingError):
            extract_terraform_config(str(tf))


class TestBuildResource:
    def test_basic(self):
        r = _build_resource("aws_instance", "web", {"instance_type": "t3.micro"})
        assert r["resource_type"] == "aws_instance"
        assert r["id"] == "web"
        assert r["instance_type"] == "t3.micro"

    def test_dict_value_copied(self):
        cfg = {"nested": {"a": 1}}
        r = _build_resource("type", "name", cfg)
        assert r["nested"] == {"a": 1}
        # Mutating original should not affect resource
        cfg["nested"]["a"] = 99
        assert r["nested"]["a"] == 1

    def test_list_value_copied(self):
        cfg = {"items": [1, 2, 3]}
        r = _build_resource("type", "name", cfg)
        assert r["items"] == [1, 2, 3]

    def test_tags_list_normalized(self):
        cfg = {"tags": [{"Key": "Env", "Value": "prod"}, {"Key": "Team", "Value": "platform"}]}
        r = _build_resource("aws_instance", "web", cfg)
        assert r["tags"] == {"Env": "prod", "Team": "platform"}

    def test_tags_dict_unchanged(self):
        cfg = {"tags": {"Env": "prod"}}
        r = _build_resource("aws_instance", "web", cfg)
        assert r["tags"] == {"Env": "prod"}
