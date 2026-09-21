from __future__ import annotations

import json
import os
import socket
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import ShipError


def allocate_port(app: str, apps: dict[str, dict[str, object]], start: int, end: int) -> int:
    existing = apps.get(app, {}).get("port")
    if isinstance(existing, int):
        return existing
    used = {entry.get("port") for entry in apps.values()}
    for port in range(start, end + 1):
        if port not in used:
            return port
    raise ShipError(f"no free ports in configured range {start}-{end}")


def port_is_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "apps": {}}
    value = json.loads(path.read_text())
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or not isinstance(value.get("apps"), dict)
    ):
        raise ShipError(f"invalid state file: {path}")
    return value


def atomic_write_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(state, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@contextmanager
def deployment_lock(lock_dir: Path, app: str) -> Iterator[None]:
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = lock_dir / f"{app}.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ShipError(f"another deployment of {app} is in progress") from exc
    try:
        yield
    finally:
        lock.rmdir()
