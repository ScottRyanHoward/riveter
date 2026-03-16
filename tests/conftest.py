"""Shared fixtures for the Riveter test suite."""

import pytest

from riveter.rules import Rule


@pytest.fixture
def simple_rule() -> Rule:
    """A basic rule that checks instance_type equality."""
    return Rule(
        {
            "id": "test-instance-type",
            "resource_type": "aws_instance",
            "description": "Instance type must be t3.large",
            "severity": "error",
            "assert": {"instance_type": "t3.large"},
        }
    )


@pytest.fixture
def ec2_resource() -> dict:
    return {
        "id": "my_instance",
        "resource_type": "aws_instance",
        "instance_type": "t3.large",
        "root_block_device": {"encrypted": True, "volume_size": 100},
        "tags": {"Environment": "production", "Owner": "team-infra"},
        "associate_public_ip_address": False,
    }


@pytest.fixture
def s3_resource() -> dict:
    return {
        "id": "my_bucket",
        "resource_type": "aws_s3_bucket",
        "bucket": "my-company-data",
        "versioning": {"enabled": True},
        "tags": {"Environment": "production"},
    }
