from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .bootstrap import run_bootstrap, write_local_config
from .config import Config, config_path, load_config
from .deploy import deploy, is_git_tracked
from .diagnostics import run_checks
from .errors import CommandError, ShipError
from .init_app import generated_files, initialize
from .manifest import validate_application, validate_name
from .remote import Remote
from .runner import SubprocessRunner


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ssh-target")
    common.add_argument("--bootstrap-target")
    common.add_argument("--server-ipv4")
    common.add_argument("--base-domain")
    common.add_argument("--remote-root")
    root = argparse.ArgumentParser(prog="ship", description="Publish small applications to one VPS")
    root.add_argument("--version", action="version", version="ship 0.1.0")
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[common], help="initialize an application repository")
    init.add_argument("--name")
    init.add_argument("--example", choices=["fastapi"])
    init.add_argument("--yes", action="store_true", help="confirm overwriting generated files")
    init.add_argument("--dry-run", action="store_true")
    init.add_argument("--json", action="store_true")

    bootstrap = sub.add_parser("bootstrap", parents=[common], help="configure the existing VPS")
    bootstrap.add_argument("--dry-run", action="store_true")
    bootstrap.add_argument("--json", action="store_true")
    bootstrap.add_argument(
        "--yes", action="store_true", help="write local config without prompting"
    )

    check = sub.add_parser("check", parents=[common], help="run local, remote, DNS, and app checks")
    check.add_argument("--json", action="store_true")

    deploy_parser = sub.add_parser(
        "deploy", parents=[common], help="deploy the current application"
    )
    deploy_parser.add_argument("--dry-run", action="store_true")
    deploy_parser.add_argument("--json", action="store_true")

    list_parser = sub.add_parser("list", parents=[common], help="list deployed applications")
    list_parser.add_argument("--json", action="store_true")
    status = sub.add_parser("status", parents=[common], help="show application status")
    status.add_argument("app", nargs="?")
    status.add_argument("--json", action="store_true")
    logs = sub.add_parser("logs", parents=[common], help="show application container logs")
    logs.add_argument("app")
    logs.add_argument("--follow", action="store_true")
    restart = sub.add_parser("restart", parents=[common], help="restart an application")
    restart.add_argument("app")
    restart.add_argument("--dry-run", action="store_true")
    restart.add_argument("--json", action="store_true")
    remove = sub.add_parser(
        "remove", parents=[common], help="remove an application route/container"
    )
    remove.add_argument("app")
    remove.add_argument("--delete-data", action="store_true")
    remove.add_argument("--yes", action="store_true")
    remove.add_argument("--dry-run", action="store_true")
    remove.add_argument("--json", action="store_true")
    return root


def _config(args: argparse.Namespace) -> Config:
    return load_config(
        overrides={
            "ssh_target": getattr(args, "ssh_target", None),
            "bootstrap_target": getattr(args, "bootstrap_target", None),
            "server_ipv4": getattr(args, "server_ipv4", None),
            "base_domain": getattr(args, "base_domain", None),
            "remote_root": getattr(args, "remote_root", None),
        }
    )


def _emit(value: Any, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(value, sort_keys=True))
        return
    if isinstance(value, list):
        for item in value:
            _emit(item, json_mode=False)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {"runtime", "config_text"}:
                print(f"{key}: {item}")
    else:
        print(value)


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    print(f"{prompt} [y/N] ", end="", file=sys.stderr, flush=True)
    return input().strip().lower() in {"y", "yes"}


def _remote_json(remote: Remote, args: list[str]) -> Any:
    result = remote.run(args)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CommandError("remote returned malformed JSON") from exc


def _removal_plan(config: Config, app: str, delete_data: bool) -> dict[str, Any]:
    base = f"{config.remote_root}/apps/{app}"
    return {
        "dry_run": True,
        "app": app,
        "container": f"ship-{app}",
        "caddy_file": f"/etc/caddy/apps/{app}.caddy",
        "preserved": [f"{base}/secrets", f"{config.remote_root}/releases/{app}"],
        "deleted_paths": [f"{base}/data"] if delete_data else [],
    }


def execute(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    cfg = _config(args)
    runner = SubprocessRunner()
    root = Path.cwd()
    json_mode = bool(getattr(args, "json", False))

    if args.command == "init":
        name = args.name or root.name.lower().replace("_", "-")
        validate_name(name)
        preview = generated_files(root, name, cfg.base_domain, args.example == "fastapi")
        existing = [path for path in preview if path.exists()]
        overwrite = args.yes
        if existing and not overwrite and not args.dry_run:
            overwrite = _confirm("Overwrite: " + ", ".join(path.name for path in existing) + "?")
        if args.dry_run:
            _emit(
                {
                    "dry_run": True,
                    "files": [str(path) for path in preview],
                    "would_overwrite": [str(path) for path in existing],
                },
                json_mode=json_mode,
            )
        else:
            files = initialize(
                root, name, cfg.base_domain, example=args.example == "fastapi", overwrite=overwrite
            )
            _emit({"initialized": name, "files": files}, json_mode=json_mode)
        return 0

    if args.command == "bootstrap":
        if args.dry_run:
            # A dry bootstrap deliberately performs the read-only remote probe.
            result = run_bootstrap(cfg, runner, dry_run=True)
        else:
            result = run_bootstrap(cfg, runner, dry_run=False)
            selected = config_path()
            if not selected.exists() and (
                args.yes or _confirm(f"Write local configuration to {selected}?")
            ):
                write_local_config(cfg, selected)
                result["config_written"] = str(selected)
            elif selected.exists():
                result["config_written"] = "existing config preserved"
            else:
                result["config_written"] = False
        _emit(result, json_mode=json_mode)
        return 0

    if args.command == "check":
        checks = run_checks(root, cfg, runner)
        if json_mode:
            _emit(
                {
                    "checks": [item.json() for item in checks],
                    "ok": not any(item.level == "failure" for item in checks),
                },
                json_mode=True,
            )
        else:
            for item in checks:
                print(f"[{item.level.upper():7}] {item.name}: {item.message}")
                if item.fix:
                    print(f"          Fix: {item.fix}")
        return 1 if any(item.level == "failure" for item in checks) else 0

    if args.command == "deploy":
        manifest = validate_application(root, cfg.base_domain)
        if manifest.environment_file and is_git_tracked(
            root / manifest.environment_file, root, runner
        ):
            print(
                f"warning: {manifest.environment_file} is tracked by Git; remove it from Git",
                file=sys.stderr,
            )
        result = deploy(root, cfg, runner, dry_run=args.dry_run)
        _emit(result, json_mode=json_mode)
        if not args.dry_run:
            print(f"https://{manifest.domain}", file=sys.stderr if json_mode else sys.stdout)
        return 0

    if args.command in {"list", "status"}:
        remote = Remote(runner, cfg.ssh_target)
        command = "list" if args.command == "list" else "status"
        remote_args = ["/usr/local/bin/ship-remote", command]
        if args.command == "status" and args.app:
            validate_name(args.app)
            remote_args.append(args.app)
        _emit(_remote_json(remote, remote_args), json_mode=json_mode)
        return 0

    if args.command == "logs":
        validate_name(args.app)
        remote_args = ["/usr/local/bin/ship-remote", "logs", args.app]
        if args.follow:
            remote_args.append("--follow")
        log_result = Remote(runner, cfg.ssh_target).run(remote_args, stream=args.follow)
        if not args.follow:
            sys.stdout.write(log_result.stdout)
            sys.stderr.write(log_result.stderr)
        return 0

    if args.command == "restart":
        validate_name(args.app)
        if args.dry_run:
            result = {"dry_run": True, "command": "docker restart", "container": f"ship-{args.app}"}
        else:
            result = _remote_json(
                Remote(runner, cfg.ssh_target), ["/usr/local/bin/ship-remote", "restart", args.app]
            )
        _emit(result, json_mode=json_mode)
        return 0

    if args.command == "remove":
        validate_name(args.app)
        plan = _removal_plan(cfg, args.app, args.delete_data)
        if args.dry_run:
            _emit(plan, json_mode=json_mode)
            return 0
        if args.delete_data and not args.yes:
            paths = ", ".join(plan["deleted_paths"])
            if not _confirm(
                f"Permanently delete {paths}? This cannot be recovered without a backup"
            ):
                raise ShipError(
                    "data deletion cancelled; use --yes for non-interactive confirmation"
                )
        remove_args = ["/usr/local/bin/ship-remote", "remove", args.app]
        if args.delete_data:
            remove_args.append("--delete-data")
        _emit(_remote_json(Remote(runner, cfg.ssh_target), remove_args), json_mode=json_mode)
        return 0
    raise ShipError(f"unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> None:
    try:
        raise SystemExit(execute(argv))
    except (ShipError, OSError) as exc:
        print(f"ship: {exc}", file=sys.stderr)
        if isinstance(exc, CommandError) and exc.output:
            print(exc.output, file=sys.stderr)
        raise SystemExit(2) from None
