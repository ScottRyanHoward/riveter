#!/usr/bin/env python3
"""Build the riveter standalone binary using PyInstaller.

Usage:
    python build_binary.py

Output:
    dist/riveter   — standalone executable (no Python required to run)

The binary does NOT bundle rule packs. Rule packs are installed separately
(e.g. via Homebrew) and are discovered at runtime from well-known directories.
"""

import subprocess
import sys
from pathlib import Path

ENTRY = Path("_riveter_entry.py")


def _anthropic_installed() -> bool:
    """Return True if the anthropic package is available in the current environment."""
    try:
        import importlib.util

        return importlib.util.find_spec("anthropic") is not None
    except Exception:
        return False


def main() -> None:
    # Write a minimal entry-point script that PyInstaller will bundle.
    ENTRY.write_text("from riveter.cli import main\nmain()\n")

    with_ai = _anthropic_installed()
    if with_ai:
        print("anthropic package found — AI explanation feature will be included in the binary.")
    else:
        print(
            "anthropic package not found — binary will be built without AI explanation support.\n"
            "To include it: pip install anthropic, then re-run this script."
        )

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "riveter",
        "--clean",
        "--noconfirm",
        # Collect data files from hcl2 (bundles hcl2.lark grammar file)
        "--collect-data",
        "hcl2",
        # Collect data files from lark (may have its own grammar files)
        "--collect-data",
        "lark",
        # Hidden imports that PyInstaller may not auto-detect
        "--hidden-import",
        "hcl2",
        "--hidden-import",
        "yaml",
        "--hidden-import",
        "click",
        "--hidden-import",
        "rich",
    ]

    if with_ai:
        # anthropic is lazily imported inside a try/except, so PyInstaller won't
        # detect it via static analysis. --collect-all bundles the full package
        # tree (code + data files); --hidden-import ensures the top-level module
        # is included even though it's never imported at the module scope.
        cmd += [
            "--collect-all",
            "anthropic",
            "--hidden-import",
            "anthropic",
            # anthropic uses httpx as its HTTP client; collect it fully so
            # certificate verification and connection adapters are available.
            "--collect-all",
            "httpx",
            "--hidden-import",
            "httpx",
        ]

    cmd.append(str(ENTRY))

    try:
        subprocess.run(cmd, check=True)
    finally:
        ENTRY.unlink(missing_ok=True)

    binary = Path("dist") / "riveter"
    if binary.exists():
        size_mb = binary.stat().st_size / 1024 / 1024
        print(f"\nBinary built: {binary} ({size_mb:.1f} MB)")
    else:
        print("\nERROR: Binary not found in dist/", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
