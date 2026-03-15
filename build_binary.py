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


def main() -> None:
    # Write a minimal entry-point script that PyInstaller will bundle.
    ENTRY.write_text("from riveter.cli import main\nmain()\n")

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--onefile",
                "--name", "riveter",
                "--clean",
                "--noconfirm",
                # Hidden imports that PyInstaller may not auto-detect
                "--hidden-import", "hcl2",
                "--hidden-import", "yaml",
                "--hidden-import", "click",
                "--hidden-import", "rich",
                str(ENTRY),
            ],
            check=True,
        )
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
