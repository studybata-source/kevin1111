from __future__ import annotations

import os
import shutil
from pathlib import Path


def find_executable(binary_name: str) -> str | None:
    direct_match = shutil.which(binary_name)
    if direct_match:
        return direct_match

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    packages_dir = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    if not packages_dir.exists():
        return None

    pattern = f"**/{binary_name}.exe"
    for candidate in packages_dir.glob(pattern):
        if candidate.is_file():
            return str(candidate)
    return None


def ensure_executable_parent_on_path(executable_path: str | None) -> None:
    if not executable_path:
        return

    executable_dir = str(Path(executable_path).parent)
    current_path = os.environ.get("PATH", "")
    normalized_entries = {entry.lower() for entry in current_path.split(os.pathsep) if entry}
    if executable_dir.lower() in normalized_entries:
        return
    os.environ["PATH"] = os.pathsep.join([executable_dir, current_path]) if current_path else executable_dir
