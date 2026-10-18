"""Apply only reviewed artwork files; validate every existing file before writing."""

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("project", type=Path, help="Path to the Android DiscGolf project")
parser.add_argument(
    "--apply",
    action="store_true",
    help="Apply changes after validation (default: check only)",
)
args = parser.parse_args()
root = args.project.resolve()
if not (root / "app/src/main/AndroidManifest.xml").is_file():
    parser.error(
        "Expected an Android project containing app/src/main/AndroidManifest.xml"
    )

with ZipFile(Path(__file__).with_name("android-artwork-update.zip")) as archive:
    records = json.loads(archive.read("manifest.json"))
    changes = []
    for record in records:
        relative = Path(record["path"])
        target = root / relative
        if (
            relative.is_absolute()
            or not target.resolve().is_relative_to(root)
            or target.is_symlink()
        ):
            raise SystemExit(f"Unsafe destination: {relative}")
        data = archive.read(relative.as_posix())
        if hashlib.sha256(data).hexdigest() != record["after"]:
            raise SystemExit(f"Bundle checksum mismatch: {relative}")
        current = (
            hashlib.sha256(target.read_bytes()).hexdigest()
            if target.is_file()
            else None
        )
        if current == record["after"]:
            continue
        if current != record["before"]:
            raise SystemExit(
                f"Stopped without changes: {relative} differs from the inspected version. Rebase the artwork change first."
            )
        changes.append((relative, target, data))
    print(f"Validated {len(records)} files; {len(changes)} changes needed.")
    if not args.apply:
        print("Check only. Add --apply to install the validated artwork update.")
    elif changes:
        backup = root / (
            ".chainlink-artwork-backup-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        )
        for relative, target, _ in changes:
            if target.is_file():
                old = backup / relative
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, old)
        for _, target, data in changes:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        print(f"Applied artwork update. Original files are backed up in {backup}.")
