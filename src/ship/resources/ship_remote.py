#!/usr/bin/env python3
"""Server-side implementation. Its stdin JSON never contains environment values."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

PLATFORM_CONFIG = Path("/etc/ship/config.json")
ROOT = Path(json.loads(PLATFORM_CONFIG.read_text()).get("remote_root", "/srv/ship"))
STATE = ROOT / "state/apps.json"
LOCKS = ROOT / "state/locks"
CADDY_STAGING = ROOT / "state/caddy"
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def run(
    args: list[str], *, check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, capture_output=capture, check=check)
    except subprocess.CalledProcessError as exc:
        detail = "\n".join(
            part.strip() for part in (exc.stdout, exc.stderr) if part and part.strip()
        )
        raise RuntimeError(f"command failed: {args[0]}\n{detail}".rstrip()) from exc


def state() -> dict[str, Any]:
    if not STATE.exists():
        return {"version": 1, "apps": {}}
    value = json.loads(STATE.read_text())
    if value.get("version") != 1 or not isinstance(value.get("apps"), dict):
        raise RuntimeError("invalid platform state")
    return cast(dict[str, Any], value)


def save(value: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".apps.json.", dir=STATE.parent, text=True)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o600)
        os.replace(name, STATE)
    finally:
        Path(name).unlink(missing_ok=True)


def valid_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise RuntimeError("invalid application name")
    return name


@contextmanager
def lock(name: str) -> Iterator[None]:
    LOCKS.mkdir(parents=True, exist_ok=True)
    path = LOCKS / f"{valid_name(name)}.lock"
    try:
        path.mkdir()
    except FileExistsError as exc:
        raise RuntimeError(f"another deployment of {name} is in progress") from exc
    try:
        yield
    finally:
        path.rmdir()


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def allocate(value: dict[str, Any], name: str, start: int, end: int) -> int:
    current = value["apps"].get(name, {}).get("port")
    if isinstance(current, int):
        return current
    used = {item.get("port") for item in value["apps"].values()}
    for port in range(start, end + 1):
        if port not in used and port_free(port):
            return port
    raise RuntimeError("no unallocated, available host port")


def command_lock(action: str, name: str, token: str) -> dict[str, Any]:
    valid_name(name)
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise RuntimeError("invalid lock token")
    LOCKS.mkdir(parents=True, exist_ok=True)
    path = LOCKS / f"{name}.lock"
    token_file = path / "token"
    if action == "acquire":
        try:
            path.mkdir()
        except FileExistsError as exc:
            raise RuntimeError(f"another deployment of {name} is in progress") from exc
        token_file.write_text(token)
        os.chmod(token_file, 0o600)
    elif action == "release":
        if not token_file.is_file() or token_file.read_text() != token:
            raise RuntimeError("deployment lock token does not match")
        token_file.unlink()
        path.rmdir()
    else:
        raise RuntimeError("unknown lock action")
    return {"name": name, "lock": action}


def require_lock(name: str, token: str) -> None:
    token_file = LOCKS / f"{valid_name(name)}.lock" / "token"
    if not token_file.is_file() or token_file.read_text() != token:
        raise RuntimeError("deployment lock is not held by this operation")


def docker_run_args(
    config: dict[str, Any], image: str, container: str, host_port: int, data_path: Path
) -> list[str]:
    args = [
        "docker",
        "run",
        "-d",
        "--name",
        container,
        "--restart",
        "unless-stopped",
        "--memory",
        config["memory"],
        "--cpus",
        str(config["cpus"]),
        "-p",
        f"127.0.0.1:{host_port}:{config['container_port']}",
    ]
    env_file = config.get("environment_remote")
    if env_file:
        args.extend(["--env-file", env_file])
    if config["data_enabled"]:
        args.extend(["-v", f"{data_path}:{config['data_path']}"])
    args.append(image)
    return args


def wait_healthy(port: int, path: str, container: str, attempts: int = 30) -> None:
    url = f"http://127.0.0.1:{port}{path}"
    for _ in range(attempts):
        result = run(["curl", "-fsS", "--max-time", "2", url], check=False)
        if result.returncode == 0:
            return
        status = run(["docker", "inspect", "-f", "{{.State.Running}}", container], check=False)
        if status.returncode != 0 or status.stdout.strip() != "true":
            break
        time.sleep(1)
    logs = run(["docker", "logs", "--tail", "100", container], check=False)
    detail = (logs.stderr + logs.stdout).strip()
    raise RuntimeError(f"health check failed for {url}\n{detail}")


def remove_container(name: str) -> None:
    run(["docker", "rm", "-f", name], check=False)


def command_prepare(payload: dict[str, Any]) -> dict[str, Any]:
    name = valid_name(payload["name"])
    require_lock(name, payload["lock_token"])
    release = payload["release"]
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z(?:-[0-9a-f]{7,40})?", release):
        raise RuntimeError("invalid release ID")
    release_dir = ROOT / "releases" / name / release
    app_dir = ROOT / "apps" / name
    release_dir.mkdir(parents=True, exist_ok=False)
    (app_dir / "data").mkdir(parents=True, exist_ok=True)
    (app_dir / "secrets").mkdir(parents=True, exist_ok=True)
    return {"release_dir": str(release_dir), "secrets_dir": str(app_dir / "secrets")}


def command_deploy(config: dict[str, Any]) -> dict[str, Any]:
    name = valid_name(config["name"])
    require_lock(name, config["lock_token"])
    release = config["release"]
    release_dir = ROOT / "releases" / name / release
    if not release_dir.is_dir():
        raise RuntimeError("release directory is missing")
    app_dir = ROOT / "apps" / name
    production = f"ship-{name}"
    candidate = f"ship-{name}-candidate-{release.lower()}"
    image = f"ship-{name}:{release}"
    if True:
        platform = state()
        prior = platform["apps"].get(name)
        port = allocate(platform, name, int(config["port_start"]), int(config["port_end"]))
        run(["docker", "build", "--pull", "-t", image, str(release_dir)])
        candidate_port = next((p for p in range(20000, 30000) if port_free(p)), None)
        if candidate_port is None:
            raise RuntimeError("no temporary candidate port available")
        temporary_data = Path(tempfile.mkdtemp(prefix=f"ship-{name}-candidate-"))
        try:
            run(docker_run_args(config, image, candidate, candidate_port, temporary_data))
            try:
                wait_healthy(candidate_port, config["healthcheck"], candidate)
            finally:
                remove_container(candidate)
        finally:
            shutil.rmtree(temporary_data, ignore_errors=True)

        if not port_free(port):
            existing = run(["docker", "inspect", "-f", "{{.Name}}", production], check=False)
            if existing.returncode != 0:
                raise RuntimeError(f"allocated port {port} is occupied by another process")
        remove_container(production)
        try:
            run(docker_run_args(config, image, production, port, app_dir / "data"))
            wait_healthy(port, config["healthcheck"], production)
        except BaseException as failure:
            remove_container(production)
            recovered = False
            if prior and prior.get("image"):
                try:
                    old_config = prior["runtime"]
                    run(
                        docker_run_args(
                            old_config, prior["image"], production, port, app_dir / "data"
                        )
                    )
                    wait_healthy(port, old_config["healthcheck"], production)
                    recovered = True
                except BaseException:
                    recovered = False
            status = (
                "previous release restored" if recovered else "previous release recovery failed"
            )
            raise RuntimeError(f"production start failed; {status}: {failure}") from failure

        CADDY_STAGING.mkdir(parents=True, exist_ok=True)
        caddy_source = CADDY_STAGING / f"{name}.caddy"
        caddy_source.write_text(f"{config['domain']} {{\n    reverse_proxy 127.0.0.1:{port}\n}}\n")
        try:
            run(["sudo", "/usr/local/sbin/ship-caddy", "install", name, str(caddy_source)])
        except BaseException:
            remove_container(production)
            if prior and prior.get("image"):
                old_config = prior["runtime"]
                run(docker_run_args(old_config, prior["image"], production, port, app_dir / "data"))
                wait_healthy(port, old_config["healthcheck"], production)
            raise

        current_new = app_dir / ".current.new"
        current = app_dir / "current"
        current_new.unlink(missing_ok=True)
        current_new.symlink_to(release_dir)
        os.replace(current_new, current)
        now = dt.datetime.now(dt.UTC).isoformat()
        runtime_config = {key: value for key, value in config.items() if key != "lock_token"}
        if runtime_config.get("environment_remote"):
            staged_environment = Path(runtime_config["environment_remote"])
            final_environment = app_dir / "secrets/environment"
            os.replace(staged_environment, final_environment)
            os.chmod(final_environment, 0o600)
            runtime_config["environment_remote"] = str(final_environment)
        platform["apps"][name] = {
            "name": name,
            "domain": config["domain"],
            "release": release,
            "image": image,
            "container": production,
            "port": port,
            "data_path": str(app_dir / "data"),
            "deployed_at": now,
            "runtime": runtime_config,
        }
        save(platform)
        releases = sorted((ROOT / "releases" / name).iterdir(), reverse=True)
        for old_release in releases[int(config["retain_releases"]) :]:
            shutil.rmtree(old_release)
            run(["docker", "image", "rm", f"ship-{name}:{old_release.name}"], check=False)
        return {**platform["apps"][name], "health": "healthy", "status": "running"}


def inspect_app(item: dict[str, Any]) -> dict[str, Any]:
    result = run(["docker", "inspect", "-f", "{{.State.Status}}", item["container"]], check=False)
    status = result.stdout.strip() if result.returncode == 0 else "missing"
    health = "unknown"
    if status == "running":
        runtime = item["runtime"]
        probe = run(
            [
                "curl",
                "-fsS",
                "--max-time",
                "2",
                f"http://127.0.0.1:{item['port']}{runtime['healthcheck']}",
            ],
            check=False,
        )
        health = "healthy" if probe.returncode == 0 else "unhealthy"
    return {key: value for key, value in item.items() if key != "runtime"} | {
        "container_status": status,
        "health": health,
    }


def command_status(name: str | None) -> Any:
    apps = state()["apps"]
    if name:
        valid_name(name)
        if name not in apps:
            raise RuntimeError(f"unknown application: {name}")
        return inspect_app(apps[name])
    return [inspect_app(apps[key]) for key in sorted(apps)]


def command_remove(name: str, delete_data: bool) -> dict[str, Any]:
    valid_name(name)
    with lock(name):
        value = state()
        item = value["apps"].get(name)
        remove_container(f"ship-{name}")
        run(["sudo", "/usr/local/sbin/ship-caddy", "remove", name])
        value["apps"].pop(name, None)
        save(value)
        if delete_data:
            data = ROOT / "apps" / name / "data"
            if data.parent.parent != ROOT / "apps" or data.name != "data":
                raise RuntimeError("refusing unsafe data path")
            shutil.rmtree(data, ignore_errors=True)
        return {"name": name, "removed": item is not None, "data_deleted": delete_data}


def main() -> None:
    try:
        command = sys.argv[1] if len(sys.argv) > 1 else ""
        if command in {"prepare", "deploy"}:
            payload = json.load(sys.stdin)
            result = command_prepare(payload) if command == "prepare" else command_deploy(payload)
        elif command in {"list", "status"}:
            name = sys.argv[2] if len(sys.argv) > 2 else None
            result = command_status(name)
        elif command == "lock" and len(sys.argv) == 5:
            result = command_lock(sys.argv[2], sys.argv[3], sys.argv[4])
        elif command == "logs" and len(sys.argv) in {3, 4}:
            name = valid_name(sys.argv[2])
            args = ["docker", "logs", "--tail", "200"]
            if len(sys.argv) == 4 and sys.argv[3] == "--follow":
                args.append("--follow")
            args.append(f"ship-{name}")
            raise SystemExit(subprocess.run(args).returncode)
        elif command == "restart" and len(sys.argv) == 3:
            name = valid_name(sys.argv[2])
            run(["docker", "restart", f"ship-{name}"])
            result = command_status(name)
        elif command == "remove" and len(sys.argv) in {3, 4}:
            result = command_remove(
                sys.argv[2], len(sys.argv) == 4 and sys.argv[3] == "--delete-data"
            )
        else:
            raise RuntimeError("unknown or malformed ship-remote command")
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
