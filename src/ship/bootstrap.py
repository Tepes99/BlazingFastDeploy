from __future__ import annotations

import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any

from .config import Config, render_config
from .errors import ShipError
from .remote import Remote, rsync_args
from .runner import Runner

READ_ONLY_PROBE = [
    "set -eu; . /etc/os-release; "
    'printf \'id=%s\\nversion=%s\\ncodename=%s\\narch=%s\\n\' "$ID" "$VERSION_ID" '
    '"$VERSION_CODENAME" "$(uname -m)"; df -Pk / | tail -1; '
    "ss -H -ltn '( sport = :80 or sport = :443 )' || true"
]


def bootstrap_plan(config: Config) -> dict[str, Any]:
    return {
        "dry_run": True,
        "target": config.bootstrap_target,
        "read_only_checks": ["SSH", "/etc/os-release", "architecture", "disk", "ports 80/443"],
        "changes": [
            "install Docker Engine, Buildx, and Compose from Docker's Ubuntu repository",
            "install Caddy from Caddy's official repository",
            "create deploy user and copy root authorized_keys",
            f"create {config.remote_root} platform directories and /etc/caddy/apps",
            "install ship remote and narrowly scoped Caddy helpers",
            "configure Caddy import, validate it, and enable Docker/Caddy",
            f"test a separate SSH connection to {config.ssh_target}",
            "offer to write the local config only after the connection succeeds",
        ],
        "commands": [
            "read-only SSH probe",
            "rsync bootstrap resources",
            "run bootstrap.sh as root",
        ],
    }


def run_bootstrap(config: Config, runner: Runner, *, dry_run: bool) -> dict[str, Any]:
    root = Remote(runner, config.bootstrap_target)
    root.probe()
    probe = root.run(["sh", "-c", READ_ONLY_PROBE[0]])
    if dry_run:
        result = bootstrap_plan(config)
        result["probe"] = probe.stdout.strip()
        return result
    resource_dir = files("ship").joinpath("resources")
    with tempfile.TemporaryDirectory(prefix="ship-bootstrap-") as temporary:
        staging = Path(temporary)
        for name in ("bootstrap.sh", "ship_remote.py", "ship_caddy.py"):
            staging.joinpath(name).write_bytes(resource_dir.joinpath(name).read_bytes())
        destination = "/tmp/ship-bootstrap"
        root.run(["rm", "-rf", "--", destination])
        root.run(["mkdir", "-m", "0700", "--", destination])
        args = rsync_args(staging, config.bootstrap_target, destination)
        # Bootstrap resources are explicit; the standard source exclusions are harmless.
        runner.run(args)
        root.run(["bash", f"{destination}/bootstrap.sh", "deploy", config.remote_root])
        root.run(["rm", "-rf", "--", destination], check=False)
    deploy = Remote(runner, config.ssh_target)
    deploy.probe()
    verified = deploy.run(["id", "-u"])
    return {
        "ready": True,
        "bootstrap_target": config.bootstrap_target,
        "deployment_target": config.ssh_target,
        "deploy_uid": verified.stdout.strip(),
        "config_text": render_config(config),
    }


def write_local_config(config: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        raise ShipError(f"refusing to overwrite existing config: {path}")
    path.write_text(render_config(config))
    path.chmod(0o600)
