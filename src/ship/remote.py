from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path

from .errors import CommandError
from .runner import Result, Runner


def validate_ssh_target(target: str) -> None:
    if not target or target.startswith("-") or any(c.isspace() for c in target):
        raise CommandError("SSH target contains unsafe characters")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@._-:[]")
    if any(c not in allowed for c in target):
        raise CommandError("SSH target contains unsafe characters")


def ssh_args(target: str, remote_args: Sequence[str], *, connect_timeout: int = 10) -> list[str]:
    validate_ssh_target(target)
    if not remote_args or any("\x00" in arg or "\n" in arg or "\r" in arg for arg in remote_args):
        raise CommandError("remote command contains invalid characters")
    # OpenSSH joins trailing arguments through a remote shell. shlex.join makes each
    # argument one literal POSIX-shell word; callers never interpolate shell fragments.
    command = shlex.join(list(remote_args))
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "--",
        target,
        command,
    ]


class Remote:
    def __init__(self, runner: Runner, target: str) -> None:
        validate_ssh_target(target)
        self.runner = runner
        self.target = target

    def run(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        check: bool = True,
        stream: bool = False,
    ) -> Result:
        return self.runner.run(
            ssh_args(self.target, args), input_text=input_text, check=check, stream=stream
        )

    def probe(self) -> Result:
        return self.run(["true"])


RSYNC_EXCLUDES = (
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "*.duckdb",
    "*.duckdb.wal",
    ".env",
    ".env.*",
    "data",
)


def rsync_args(source: Path, target: str, destination: str, *, dry_run: bool = False) -> list[str]:
    validate_ssh_target(target)
    if not destination.startswith("/") or ".." in Path(destination).parts:
        raise CommandError("unsafe rsync destination")
    args = ["rsync", "-az", "--delete"]
    if dry_run:
        args.append("--dry-run")
    for pattern in RSYNC_EXCLUDES:
        args.extend(["--exclude", pattern])
    args.extend([f"{source.resolve()}/", f"{target}:{destination}/"])
    return args


def environment_rsync_args(source: Path, target: str, destination: str) -> list[str]:
    validate_ssh_target(target)
    if not destination.startswith("/") or ".." in Path(destination).parts:
        raise CommandError("unsafe environment destination")
    return [
        "rsync",
        "-az",
        "--chmod=F600",
        str(source.resolve()),
        f"{target}:{destination}",
    ]
