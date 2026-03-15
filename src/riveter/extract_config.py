"""Extract Terraform HCL configuration into Riveter's internal resource format.

The output is a dict with a single ``resources`` key containing a list of
resource dicts, each with at minimum:

    {
        "id": "<terraform resource name>",
        "resource_type": "<terraform resource type>",
        ... (all top-level attributes from the HCL resource block)
    }
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import hcl2

from .exceptions import FileSystemError, TerraformParsingError

log = logging.getLogger(__name__)

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def extract_terraform_config(tf_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse a Terraform file and return a normalized resource list.

    Supports both single files and directories. When a directory is given every
    ``.tf`` file inside it is parsed and the resources are merged.

    Args:
        tf_path: Path to a ``.tf`` file or a directory of ``.tf`` files.

    Returns:
        ``{"resources": [...]}``.

    Raises:
        FileSystemError: When the path does not exist or cannot be read.
        TerraformParsingError: When HCL parsing fails.
    """
    path = Path(tf_path)

    if not path.exists():
        raise FileSystemError(
            f"Path not found: {tf_path}",
            file_path=tf_path,
            suggestions=["Check that the path is correct and the file exists."],
        )

    if path.is_dir():
        tf_files = sorted(path.glob("**/*.tf"))
        if not tf_files:
            log.warning("No .tf files found in %s", tf_path)
            return {"resources": []}
        resources: List[Dict[str, Any]] = []
        for f in tf_files:
            resources.extend(_parse_file(str(f)))
        return {"resources": resources}

    return {"resources": _parse_file(tf_path)}


def _parse_file(tf_file: str) -> List[Dict[str, Any]]:
    """Parse a single Terraform file and return its resource list."""
    resolved = Path(os.path.realpath(tf_file))

    if not resolved.is_file():
        raise FileSystemError(f"Not a file: {tf_file}", file_path=tf_file)

    size = resolved.stat().st_size
    if size > _MAX_FILE_SIZE:
        raise FileSystemError(
            f"File exceeds 10 MB limit: {tf_file} ({size} bytes)",
            file_path=tf_file,
            suggestions=["Split large Terraform configs into smaller files."],
        )

    log.debug("Parsing %s (%d bytes)", tf_file, size)

    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            content = fh.read()
        if not content.strip():
            log.warning("Empty Terraform file: %s", tf_file)
            return []
        tf_config = hcl2.loads(content)
    except UnicodeDecodeError as exc:
        raise TerraformParsingError(
            f"Encoding error in {tf_file}: {exc}",
            terraform_file=tf_file,
        ) from exc
    except Exception as exc:
        raise TerraformParsingError(
            f"Failed to parse {tf_file}: {exc}",
            terraform_file=tf_file,
        ) from exc

    if "resource" not in tf_config:
        log.debug("No resource blocks in %s", tf_file)
        return []

    resources: List[Dict[str, Any]] = []
    for resource_block in tf_config["resource"]:
        for resource_type, instances in resource_block.items():
            for name, config in instances.items():
                try:
                    resource = _build_resource(resource_type, name, config)
                    resources.append(resource)
                    log.debug("Extracted %s.%s", resource_type, name)
                except Exception as exc:
                    log.warning("Skipping %s.%s: %s", resource_type, name, exc)

    return resources


def _build_resource(
    resource_type: str, name: str, config: Dict[str, Any]
) -> Dict[str, Any]:
    """Flatten a single HCL resource block into a Riveter resource dict."""
    resource: Dict[str, Any] = {"id": name, "resource_type": resource_type}

    for key, value in config.items():
        if isinstance(value, dict):
            resource[key] = dict(value)
        elif isinstance(value, list):
            resource[key] = list(value)
        else:
            resource[key] = value

    # Normalize tags: HCL sometimes emits them as a list of {Key, Value} dicts
    if "tags" in resource and isinstance(resource["tags"], list):
        tags_dict: Dict[str, Any] = {}
        for tag in resource["tags"]:
            if isinstance(tag, dict) and "Key" in tag and "Value" in tag:
                tags_dict[tag["Key"]] = tag["Value"]
        if tags_dict:
            resource["tags"] = tags_dict

    return resource
