"""Extract deployed resource data from a Terraform state file.

The output mirrors the format produced by ``extract_config.py`` so the
existing scanner and formatters can consume state results without
modification:

    {
        "id": "<type>.<name>",           # or "<module>.<type>.<name>[<index>]"
        "resource_type": "<tf type>",
        ... (all attributes from the state instance's attributes block)
    }

Only *managed* resources (``"mode": "managed"``) are included. Data sources
(``"mode": "data"``) are skipped because they represent read-only lookups, not
deployed infrastructure you control.

State format version 4 or later is required (introduced in Terraform 0.13+).
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .exceptions import FileSystemError, TerraformParsingError

log = logging.getLogger(__name__)

_MAX_STATE_SIZE = 50 * 1024 * 1024  # 50 MB
_MIN_STATE_VERSION = 4


def extract_terraform_state(path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse a Terraform state file and return a normalized resource list.

    Args:
        path: Path to a ``terraform.tfstate`` JSON file, or ``"-"`` to read
              from stdin (e.g. piped from ``terraform state pull``).

    Returns:
        ``{"resources": [...]}``.

    Raises:
        FileSystemError: When the file does not exist, cannot be read, or
            exceeds the 50 MB size limit.
        TerraformParsingError: When the JSON is invalid or the state format
            version is not supported.
    """
    if path == "-":
        return _parse_state(_read_stdin(), source="<stdin>")

    state_path = Path(path).resolve()

    if not state_path.exists():
        raise FileSystemError(
            f"State file not found: {path}",
            file_path=path,
            suggestions=[
                "Check that the path is correct and the file exists.",
                "Run 'terraform state pull > terraform.tfstate' to export remote state.",
            ],
        )

    if not state_path.is_file():
        raise FileSystemError(
            f"Not a file: {path}",
            file_path=path,
        )

    size = state_path.stat().st_size
    if size > _MAX_STATE_SIZE:
        raise FileSystemError(
            f"State file exceeds 50 MB limit: {path} ({size} bytes)",
            file_path=path,
            suggestions=[
                "Consider splitting your Terraform configuration into smaller workspaces."
            ],
        )

    log.debug("Parsing state file %s (%d bytes)", path, size)

    try:
        raw = state_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise TerraformParsingError(
            f"Encoding error reading state file {path}: {exc}",
            terraform_file=path,
        ) from exc

    return _parse_state(raw, source=path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_stdin() -> str:
    """Read the full contents of stdin as a string."""
    return sys.stdin.read()


def _parse_state(raw: str, source: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse raw state JSON and return ``{"resources": [...]}``.

    Args:
        raw:    Full JSON text of the state file.
        source: Human-readable label for error messages (file path or "<stdin>").
    """
    try:
        state: Dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TerraformParsingError(
            f"Failed to parse state JSON from {source}: {exc}",
            terraform_file=source,
            suggestions=[
                "Ensure the file is valid JSON.",
                "Run 'terraform state pull' to regenerate the state.",
            ],
        ) from exc

    if "version" not in state:
        raise TerraformParsingError(
            f"Unrecognized state format in {source}: missing 'version' key.",
            terraform_file=source,
            suggestions=[
                "This does not appear to be a Terraform state file.",
                "Ensure you are pointing at a 'terraform.tfstate' file.",
            ],
        )

    version = state["version"]
    if version < _MIN_STATE_VERSION:
        raise TerraformParsingError(
            f"State format version {version} is not supported (requires v{_MIN_STATE_VERSION}+).",
            terraform_file=source,
            suggestions=[
                f"Upgrade to Terraform 0.13+ and run 'terraform apply' to migrate the state "
                f"to format version {_MIN_STATE_VERSION}.",
            ],
        )

    resources: List[Dict[str, Any]] = []

    for res in state.get("resources", []):
        if res.get("mode") != "managed":
            # Skip data sources and any future resource modes
            log.debug(
                "Skipping %s resource %s.%s (mode=%s)",
                res.get("mode", "unknown"),
                res.get("type", ""),
                res.get("name", ""),
                res.get("mode", ""),
            )
            continue

        resource_type: str = res.get("type", "")
        name: str = res.get("name", "")
        module: Optional[str] = res.get("module") or None

        for instance in res.get("instances", []):
            attrs: Dict[str, Any] = instance.get("attributes", {})
            index_key = instance.get("index_key")

            resource_id = _build_resource_id(resource_type, name, module, index_key)

            resource: Dict[str, Any] = {
                "id": resource_id,
                "resource_type": resource_type,
            }
            # Flatten all state attributes into the resource dict
            resource.update(attrs)

            log.debug("Extracted state resource: %s", resource_id)
            resources.append(resource)

    return {"resources": resources}


def _build_resource_id(
    resource_type: str,
    name: str,
    module: Optional[str],
    index_key: Any,
) -> str:
    """Compose a resource id that matches the HCL convention used by extract_config.py.

    The id is the resource *name* (optionally prefixed by the module path and
    suffixed by the instance index), WITHOUT the resource type. This allows
    ``_display_table`` in cli.py to prepend ``resource_type`` and produce a
    correctly formatted ``aws_instance.web`` label — the same as for HCL scans.

    Examples:
        web                          (simple managed resource)
        servers[0]                   (count = 2, first instance)
        env["prod"]                  (for_each with string key)
        module.vpc.web               (resource inside a module)
        module.app.web[0]            (module + count)
    """
    base = name
    if module:
        base = f"{module}.{name}"
    if index_key is not None:
        if isinstance(index_key, str):
            base = f'{base}["{index_key}"]'
        else:
            base = f"{base}[{index_key}]"
    return base
