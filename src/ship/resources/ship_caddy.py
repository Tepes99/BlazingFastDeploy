#!/usr/bin/env python3
"""Narrow privileged Caddy fragment installer used through sudo."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
APPS = Path("/etc/caddy/apps")
CADDYFILE = Path("/etc/caddy/Caddyfile")
PLATFORM_CONFIG = Path("/etc/ship/config.json")
REMOTE_ROOT = Path(json.loads(PLATFORM_CONFIG.read_text()).get("remote_root", "/srv/ship"))
ALLOWED_SOURCE = REMOTE_ROOT / "state/caddy"


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def validate(staged: Path) -> None:
    original = CADDYFILE.read_text()
    marker = "/etc/caddy/apps/*.caddy"
    if marker not in original:
        fail(f"{CADDYFILE} does not import {marker}")
    staged_config = staged / "Caddyfile"
    staged_config.write_text(original.replace(marker, f"{staged}/*.caddy"))
    subprocess.run(
        ["caddy", "validate", "--config", str(staged_config)],
        check=True,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )


def main() -> None:
    if len(sys.argv) not in {3, 4} or sys.argv[1] not in {"install", "remove"}:
        fail("usage: ship-caddy install APP SOURCE | ship-caddy remove APP")
    action, app = sys.argv[1:3]
    if not NAME_RE.fullmatch(app):
        fail("invalid application name")
    source: Path | None = None
    if action == "install":
        if len(sys.argv) != 4:
            fail("install requires a source")
        source = Path(sys.argv[3]).resolve()
        if source.parent != ALLOWED_SOURCE or source.name != f"{app}.caddy" or not source.is_file():
            fail(f"source must be the matching file in {ALLOWED_SOURCE}")
    elif len(sys.argv) != 3:
        fail("remove takes no source")

    APPS.mkdir(parents=True, exist_ok=True)
    destination = APPS / f"{app}.caddy"
    old = destination.read_bytes() if destination.exists() else None
    with tempfile.TemporaryDirectory(prefix="ship-caddy-") as temporary:
        staged = Path(temporary)
        for item in APPS.glob("*.caddy"):
            shutil.copy2(item, staged / item.name)
        staged_target = staged / destination.name
        if action == "install" and source is not None:
            shutil.copy2(source, staged_target)
        else:
            staged_target.unlink(missing_ok=True)
        validate(staged)

    try:
        if action == "install" and source is not None:
            temporary_target = APPS / f".{app}.caddy.new"
            shutil.copyfile(source, temporary_target)
            os.chown(temporary_target, 0, 0)
            os.chmod(temporary_target, 0o644)
            os.replace(temporary_target, destination)
        else:
            destination.unlink(missing_ok=True)
        subprocess.run(["caddy", "validate", "--config", str(CADDYFILE)], check=True)
        subprocess.run(["systemctl", "reload", "caddy"], check=True)
    except BaseException:
        if old is None:
            destination.unlink(missing_ok=True)
        else:
            rollback = APPS / f".{app}.caddy.rollback"
            rollback.write_bytes(old)
            os.chown(rollback, 0, 0)
            os.chmod(rollback, 0o644)
            os.replace(rollback, destination)
        raise


if __name__ == "__main__":
    main()
