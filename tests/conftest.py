from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ship.runner import Result


class FakeRunner:
    def __init__(self, responses: list[Result] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        check: bool = True,
        cwd: Path | None = None,
        stream: bool = False,
    ) -> Result:
        del input_text, check, cwd, stream
        call = tuple(args)
        self.calls.append(call)
        if self.responses:
            return self.responses.pop(0)
        return Result(call, 0)


def write_app(root: Path, *, name: str = "medicine", environment: bool = False) -> None:
    env = '\n[environment]\nfile = ".env.production"\n' if environment else ""
    root.joinpath("ship.toml").write_text(
        f'''version = 1
name = "{name}"

[service]
container_port = 8000
healthcheck = "/health"
memory = "384m"
cpus = 0.5

[data]
enabled = true
container_path = "/data"
{env}'''
    )
    root.joinpath("Dockerfile").write_text("FROM scratch\n")
    if environment:
        root.joinpath(".env.production").write_text("TOKEN=secret\n")
