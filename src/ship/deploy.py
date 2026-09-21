from __future__ import annotations

import datetime as dt
import fnmatch
import json
import secrets
from pathlib import Path
from typing import Any, cast

from .config import Config
from .errors import CommandError, ShipError
from .manifest import Manifest, validate_application
from .remote import Remote, environment_rsync_args, rsync_args
from .runner import Runner


def git_sha(root: Path, runner: Runner) -> str | None:
    result = runner.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=root, check=False)
    sha = result.stdout.strip().lower()
    return (
        sha
        if result.returncode == 0 and sha and all(c in "0123456789abcdef" for c in sha)
        else None
    )


def release_id(root: Path, runner: Runner, now: dt.datetime | None = None) -> str:
    moment = now or dt.datetime.now(dt.UTC)
    prefix = moment.strftime("%Y%m%dT%H%M%SZ")
    sha = git_sha(root, runner)
    return f"{prefix}-{sha}" if sha else prefix


def is_git_tracked(path: Path, root: Path, runner: Runner) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    result = runner.run(
        ["git", "ls-files", "--error-unmatch", "--", str(relative)], cwd=root, check=False
    )
    return result.returncode == 0


def deployment_payload(
    manifest: Manifest, config: Config, release: str, token: str
) -> dict[str, Any]:
    app_dir = f"{config.remote_root}/apps/{manifest.name}"
    return {
        "name": manifest.name,
        "domain": manifest.domain,
        "release": release,
        "lock_token": token,
        "container_port": manifest.service.container_port,
        "healthcheck": manifest.service.healthcheck,
        "memory": manifest.service.memory,
        "cpus": manifest.service.cpus,
        "data_enabled": manifest.data.enabled,
        "data_path": manifest.data.container_path,
        "environment_remote": (
            f"{app_dir}/secrets/environment.{release}" if manifest.environment_file else None
        ),
        "port_start": config.port_start,
        "port_end": config.port_end,
        "retain_releases": config.retain_releases,
    }


def dry_run_plan(root: Path, manifest: Manifest, config: Config, release: str) -> dict[str, Any]:
    release_dir = f"{config.remote_root}/releases/{manifest.name}/{release}"
    app_dir = f"{config.remote_root}/apps/{manifest.name}"
    transferred = planned_source_files(root)
    result: dict[str, Any] = {
        "dry_run": True,
        "app": manifest.name,
        "local_files_read": [str(root / "ship.toml"), str(root / "Dockerfile")],
        "transfers": [
            {
                "source": str(root),
                "destination": release_dir,
                "files": transferred,
                "excludes": "standard",
            }
        ],
        "remote_directories": [release_dir, f"{app_dir}/data", f"{app_dir}/secrets"],
        "image": f"ship-{manifest.name}:{release}",
        "containers": [
            f"ship-{manifest.name}-candidate-{release.lower()}",
            f"ship-{manifest.name}",
        ],
        "caddy_file": f"/etc/caddy/apps/{manifest.name}.caddy",
        "commands": [
            "ssh connectivity probe",
            "ship-remote lock acquire",
            "ship-remote prepare",
            "rsync source with exclusions",
            "docker build on remote x86_64 host",
            "candidate run and loopback health check with temporary data",
            "production replacement and health check (rollback on failure)",
            "Caddy staged validation, atomic install, and reload",
            "atomic state/current update and release retention",
            "ship-remote lock release",
        ],
    }
    if manifest.environment_file:
        result["local_files_read"].append(str(root / manifest.environment_file))
        result["transfers"].append(
            {
                "source": manifest.environment_file,
                "destination": f"{app_dir}/secrets/environment.{release}",
                "mode": "0600",
            }
        )
    return result


def planned_source_files(root: Path) -> list[str]:
    from .remote import RSYNC_EXCLUDES

    included: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        excluded = any(
            fnmatch.fnmatch(part, pattern) or fnmatch.fnmatch(str(relative), pattern)
            for pattern in RSYNC_EXCLUDES
            for part in relative.parts
        )
        if not excluded:
            included.append(str(relative))
    return sorted(included)


def deploy(root: Path, config: Config, runner: Runner, *, dry_run: bool = False) -> dict[str, Any]:
    manifest = validate_application(root, config.base_domain)
    release = release_id(root, runner)
    if dry_run:
        return dry_run_plan(root, manifest, config, release)
    remote = Remote(runner, config.ssh_target)
    remote.probe()
    check = remote.run(["test", "-x", "/usr/local/bin/ship-remote"], check=False)
    if check.returncode:
        raise ShipError("server is not bootstrapped; run ship bootstrap first")
    token = secrets.token_hex(16)
    remote.run(["/usr/local/bin/ship-remote", "lock", "acquire", manifest.name, token])
    try:
        prepared = remote.run(
            ["/usr/local/bin/ship-remote", "prepare"],
            input_text=json.dumps({"name": manifest.name, "release": release, "lock_token": token}),
        )
        locations = json.loads(prepared.stdout)
        runner.run(rsync_args(root, config.ssh_target, locations["release_dir"]))
        if manifest.environment_file:
            env_path = root / manifest.environment_file
            runner.run(
                environment_rsync_args(
                    env_path,
                    config.ssh_target,
                    f"{locations['secrets_dir']}/environment.{release}",
                )
            )
        result = remote.run(
            ["/usr/local/bin/ship-remote", "deploy"],
            input_text=json.dumps(deployment_payload(manifest, config, release, token)),
        )
        parsed = json.loads(result.stdout)
        if not isinstance(parsed, dict):
            raise CommandError("remote deployment response must be an object")
        return cast(dict[str, Any], parsed)
    except (json.JSONDecodeError, KeyError) as exc:
        raise CommandError("remote returned malformed deployment data") from exc
    finally:
        remote.run(
            ["/usr/local/bin/ship-remote", "lock", "release", manifest.name, token],
            check=False,
        )


class LifecycleBackend:
    """Small test seam documenting the production replacement guarantee."""

    def start_candidate(self) -> None: ...
    def check_candidate(self) -> None: ...
    def stop_candidate(self) -> None: ...
    def stop_previous(self) -> None: ...
    def start_production(self) -> None: ...
    def check_production(self) -> None: ...
    def restore_previous(self) -> None: ...


def replace_production(backend: LifecycleBackend) -> None:
    backend.start_candidate()
    try:
        backend.check_candidate()
    finally:
        backend.stop_candidate()
    backend.stop_previous()
    try:
        backend.start_production()
        backend.check_production()
    except BaseException:
        backend.restore_previous()
        raise
