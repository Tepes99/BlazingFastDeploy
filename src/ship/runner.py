from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import CommandError


@dataclass(frozen=True)
class Result:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        check: bool = True,
        cwd: Path | None = None,
        stream: bool = False,
    ) -> Result: ...


class SubprocessRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        check: bool = True,
        cwd: Path | None = None,
        stream: bool = False,
    ) -> Result:
        completed = subprocess.run(
            list(args),
            input=input_text,
            text=True,
            capture_output=not stream,
            cwd=cwd,
            check=False,
        )
        result = Result(
            tuple(args), completed.returncode, completed.stdout or "", completed.stderr or ""
        )
        if check and completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise CommandError(
                f"command failed ({completed.returncode}): {display_args(args)}", output=detail
            )
        return result


def display_args(args: Sequence[str]) -> str:
    return shlex.join(list(args))
