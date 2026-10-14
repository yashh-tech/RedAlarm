"""Set only the Android launcher icon for RedAlarm.

This script intentionally does NOT edit main.py, alarm.kv, splash_screen.py,
services/ring_service.py, or any alarm/audio behavior. It copies the adjacent
redalarm_icon.png into the project root and updates only buildozer.spec.

Usage: run this script with the RedAlarm project root as the current folder,
with this script and redalarm_icon.png side by side (for example, from Downloads).
Compatible with Python 3.9+.
"""
from pathlib import Path
import shutil
import sys

ASSET_NAME = "redalarm_icon.png"
ICON_SETTING = "icon.filename = %(source.dir)s/redalarm_icon.png"


def backup_once(source: Path, backup: Path) -> None:
    """Keep a one-time backup outside the Git checkout."""
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(backup))


def update_spec(spec_text: str) -> str:
    """Set icon.filename within [app], preserving all other spec settings."""
    lines = spec_text.splitlines()
    app_start = next((i for i, line in enumerate(lines) if line.strip() == "[app]"), None)
    if app_start is None:
        raise RuntimeError("buildozer.spec does not contain an [app] section")

    next_section = next(
        (
            i for i in range(app_start + 1, len(lines))
            if lines[i].lstrip().startswith("[") and lines[i].rstrip().endswith("]")
        ),
        len(lines),
    )
    app_lines = lines[app_start:next_section]
    icon_indexes = [
        app_start + offset
        for offset, line in enumerate(app_lines)
        if line.strip().startswith("icon.filename") and "=" in line
    ]

    if icon_indexes:
        # Keep exactly one active icon.filename setting in [app].
        first = icon_indexes[0]
        lines[first] = ICON_SETTING
        for index in reversed(icon_indexes[1:]):
            del lines[index]
    else:
        title_index = next(
            (
                app_start + offset
                for offset, line in enumerate(app_lines)
                if line.strip().startswith("title") and "=" in line
            ),
            None,
        )
        insert_at = title_index + 1 if title_index is not None else app_start + 1
        lines.insert(insert_at, ICON_SETTING)

    result = "\n".join(lines) + ("\n" if spec_text.endswith("\n") else "")
    include_line = next(
        (line for line in result.splitlines() if line.strip().startswith("source.include_exts") and "=" in line),
        None,
    )
    if include_line is None or "png" not in include_line.split("=", 1)[1].lower():
        raise RuntimeError(
            "source.include_exts in buildozer.spec must include png; no files were changed"
        )
    return result


def main() -> int:
    root = Path.cwd().resolve()
    spec_path = root / "buildozer.spec"
    if not spec_path.is_file():
        raise RuntimeError(
            "Run this script from the RedAlarm project root, where buildozer.spec exists"
        )

    script_asset = Path(__file__).resolve().with_name(ASSET_NAME)
    project_asset = root / ASSET_NAME
    if not script_asset.is_file() and not project_asset.is_file():
        raise RuntimeError(
            "redalarm_icon.png not found beside this script or in the project root; "
            "extract both patch files into the same folder"
        )

    original_spec = spec_path.read_text(encoding="utf-8")
    updated_spec = update_spec(original_spec)
    backup_root = root.parent / (root.name + "_launcher_icon_backups")

    # Make changes only after all preflight checks have passed.
    if updated_spec != original_spec:
        backup_once(spec_path, backup_root / "buildozer.spec.bak")

    if script_asset.is_file():
        same_file = script_asset.resolve() == project_asset.resolve()
        if not same_file:
            if project_asset.exists():
                backup_once(project_asset, backup_root / (ASSET_NAME + ".bak"))
            shutil.copy2(str(script_asset), str(project_asset))
    elif not project_asset.is_file():
        raise RuntimeError("Launcher icon could not be installed")

    if updated_spec != original_spec:
        # Python 3.9 compatible; newline arg is on open(), not Path.write_text().
        with spec_path.open("w", encoding="utf-8", newline="\n") as output:
            output.write(updated_spec)

    print("[RedAlarm] Launcher-icon patch applied.")
    print("[RedAlarm] Added/set only: icon.filename in buildozer.spec")
    print("[RedAlarm] Icon asset: {}".format(project_asset))
    print("[RedAlarm] No other project source files were modified by this script.")
    if backup_root.exists():
        print("[RedAlarm] Backups (if replacements were needed): {}".format(backup_root))
    print("[RedAlarm] Verify with: git diff -- buildozer.spec; git status --short")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("[RedAlarm] ERROR: {}".format(exc), file=sys.stderr)
        raise SystemExit(1)
