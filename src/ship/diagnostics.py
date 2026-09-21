from __future__ import annotations

import json
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .config import Config
from .deploy import is_git_tracked
from .manifest import Manifest, validate_application
from .remote import Remote
from .runner import Runner

Level = Literal["passed", "warning", "failure"]


@dataclass(frozen=True)
class Check:
    name: str
    level: Level
    message: str
    fix: str | None = None

    def json(self) -> dict[str, object]:
        return asdict(self)


def _dns(name: str) -> set[str]:
    try:
        return {str(item[4][0]) for item in socket.getaddrinfo(name, None, socket.AF_INET)}
    except socket.gaierror:
        return set()


def _tcp(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def run_checks(root: Path, config: Config, runner: Runner) -> list[Check]:
    checks: list[Check] = []
    py_ok = sys.version_info >= (3, 11)
    checks.append(
        Check(
            "python",
            "passed" if py_ok else "failure",
            sys.version.split()[0],
            "Install Python 3.11 or newer" if not py_ok else None,
        )
    )
    for binary in ("ssh", "rsync"):
        found = shutil.which(binary)
        checks.append(
            Check(
                binary,
                "passed" if found else "failure",
                found or "not found",
                f"Install {binary} and ensure it is on PATH" if not found else None,
            )
        )

    manifest: Manifest | None = None
    if (root / "ship.toml").exists() or (root / "Dockerfile").exists():
        try:
            manifest = validate_application(root, config.base_domain)
            checks.append(Check("application", "passed", f"valid manifest for {manifest.name}"))
            if manifest.environment_file:
                env_path = root / manifest.environment_file
                tracked = is_git_tracked(env_path, root, runner)
                tracking = "tracked by Git" if tracked else "not tracked by Git"
                fix = (
                    f"Run: git rm --cached -- {manifest.environment_file} and add it to .gitignore"
                    if tracked
                    else None
                )
                checks.append(
                    Check(
                        "environment_git",
                        "warning" if tracked else "passed",
                        f"{manifest.environment_file} is {tracking}",
                        fix,
                    )
                )
        except Exception as exc:
            checks.append(
                Check(
                    "application",
                    "failure",
                    str(exc),
                    "Fix ship.toml and ensure Dockerfile and the declared environment file exist",
                )
            )

    base_ips = _dns(config.base_domain)
    checks.append(
        Check(
            "base_domain_dns",
            "passed" if config.server_ipv4 in base_ips else "failure",
            f"{config.base_domain} resolves to {', '.join(sorted(base_ips)) or 'nothing'}",
            f"Keep/create Route 53 record: {config.base_domain} A {config.server_ipv4}"
            if config.server_ipv4 not in base_ips
            else None,
        )
    )
    wildcard_probe = f"ship-dns-probe.{config.base_domain}"
    wildcard_ips = _dns(wildcard_probe)
    checks.append(
        Check(
            "wildcard_dns",
            "passed" if config.server_ipv4 in wildcard_ips else "failure",
            f"{wildcard_probe} resolves to {', '.join(sorted(wildcard_ips)) or 'nothing'}",
            f"Create this Route 53 record exactly: *.{config.base_domain} A {config.server_ipv4}"
            if config.server_ipv4 not in wildcard_ips
            else None,
        )
    )
    if manifest:
        app_ips = _dns(manifest.domain)
        checks.append(
            Check(
                "application_dns",
                "passed" if config.server_ipv4 in app_ips else "failure",
                f"{manifest.domain} resolves to {', '.join(sorted(app_ips)) or 'nothing'}",
                f"Create: *.{config.base_domain} A {config.server_ipv4}"
                if config.server_ipv4 not in app_ips
                else None,
            )
        )

    try:
        remote = Remote(runner, config.ssh_target)
        remote.probe()
        checks.append(Check("ssh", "passed", f"connected to {config.ssh_target}"))
        os_result = remote.run(
            ["sh", "-c", '. /etc/os-release; printf \'%s %s\' "$ID" "$VERSION_ID"']
        )
        os_ok = os_result.stdout.strip() == "ubuntu 26.04"
        checks.append(
            Check(
                "remote_os",
                "passed" if os_ok else "failure",
                os_result.stdout.strip(),
                "Bootstrap requires Ubuntu 26.04" if not os_ok else None,
            )
        )
        arch = remote.run(["uname", "-m"]).stdout.strip()
        checks.append(
            Check(
                "remote_arch",
                "passed" if arch == "x86_64" else "failure",
                arch,
                "Use the existing x86_64 VPS" if arch != "x86_64" else None,
            )
        )
        addresses = remote.run(["hostname", "-I"], check=False).stdout.split()
        public_ip_ok = config.server_ipv4 in addresses
        checks.append(
            Check(
                "public_ipv4",
                "passed" if public_ip_ok else "failure",
                ", ".join(addresses) or "no address reported",
                f"Expected the existing VPS address {config.server_ipv4}"
                if not public_ip_ok
                else None,
            )
        )
        for name, command, fix in (
            ("docker", ["docker", "info"], "Run: ship bootstrap"),
            (
                "caddy",
                ["systemctl", "is-active", "caddy"],
                "Run: ship bootstrap or sudo systemctl start caddy",
            ),
            (
                "caddy_config",
                ["caddy", "validate", "--config", "/etc/caddy/Caddyfile"],
                "Fix the reported Caddy configuration error",
            ),
        ):
            result = remote.run(command, check=False)
            checks.append(
                Check(
                    name,
                    "passed" if result.returncode == 0 else "failure",
                    "ok"
                    if result.returncode == 0
                    else (result.stderr.strip() or result.stdout.strip()),
                    None if result.returncode == 0 else fix,
                )
            )
        disk = remote.run(["df", "-Pk", config.remote_root], check=False)
        if disk.returncode:
            checks.append(
                Check("disk", "failure", "platform directory is missing", "Run: ship bootstrap")
            )
        else:
            fields = disk.stdout.splitlines()[-1].split()
            free = int(fields[3]) * 1024
            disk_ok = free >= 5 * 1024**3
            checks.append(
                Check(
                    "disk",
                    "passed" if disk_ok else "warning",
                    f"{free // 1024**3} GiB free",
                    "Free at least 5 GiB" if not disk_ok else None,
                )
            )
        all_status = remote.run(["/usr/local/bin/ship-remote", "list"], check=False)
        if all_status.returncode == 0:
            decoded = json.loads(all_status.stdout)
            app_items = decoded if isinstance(decoded, list) else []
            allocated = [
                port
                for item in app_items
                if isinstance(item, dict)
                for port in [item.get("port")]
                if isinstance(port, int)
            ]
            duplicate_ports = sorted({port for port in allocated if allocated.count(port) > 1})
            checks.append(
                Check(
                    "port_allocations",
                    "failure" if duplicate_ports else "passed",
                    f"duplicate allocations: {duplicate_ports}"
                    if duplicate_ports
                    else "allocated ports are unique",
                    "Repair duplicate ports in /srv/ship/state/apps.json before deploying"
                    if duplicate_ports
                    else None,
                )
            )
        if manifest:
            app_status = remote.run(
                ["/usr/local/bin/ship-remote", "status", manifest.name], check=False
            )
            if app_status.returncode == 0:
                decoded_app = json.loads(app_status.stdout)
                healthy = isinstance(decoded_app, dict) and decoded_app.get("health") == "healthy"
                checks.append(
                    Check(
                        "application_health",
                        "passed" if healthy else "failure",
                        decoded_app.get("health", "unknown")
                        if isinstance(decoded_app, dict)
                        else "malformed status",
                        f"Inspect: ship logs {manifest.name}" if not healthy else None,
                    )
                )
        # The remote helper checks allocated ports when it deploys. Docker's published
        # bindings below expose any unexpected collision for diagnostics.
        ports = remote.run(["docker", "ps", "--format", "{{.Names}} {{.Ports}}"], check=False)
        public = [line for line in ports.stdout.splitlines() if "0.0.0.0:" in line or ":::" in line]
        checks.append(
            Check(
                "port_bindings",
                "warning" if public else "passed",
                "; ".join(public)
                if public
                else "application containers use no detected public bindings",
                "Recreate listed app containers with ship so they bind to 127.0.0.1"
                if public
                else None,
            )
        )
    except Exception as exc:
        checks.append(Check("ssh", "failure", str(exc), f"Verify: ssh {config.ssh_target}"))

    for port in (80, 443):
        reachable = _tcp(config.server_ipv4, port)
        checks.append(
            Check(
                f"public_port_{port}",
                "passed" if reachable else "warning",
                "reachable" if reachable else "not reachable",
                f"Verify the Hetzner firewall allows TCP {port} and Caddy is running"
                if not reachable
                else None,
            )
        )
    return checks
