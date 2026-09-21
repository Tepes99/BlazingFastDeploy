from __future__ import annotations

import ipaddress
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import ValidationError


@dataclass(frozen=True)
class Config:
    ssh_target: str = "deploy@apps.teemusaha.com"
    bootstrap_target: str = "root@apps.teemusaha.com"
    server_ipv4: str = "2.29.47.65"
    base_domain: str = "apps.teemusaha.com"
    remote_root: str = "/srv/ship"
    port_start: int = 10000
    port_end: int = 19999
    retain_releases: int = 3


ENV_KEYS = {
    "SHIP_SSH_TARGET": "ssh_target",
    "SHIP_BOOTSTRAP_TARGET": "bootstrap_target",
    "SHIP_SERVER_IPV4": "server_ipv4",
    "SHIP_BASE_DOMAIN": "base_domain",
    "SHIP_REMOTE_ROOT": "remote_root",
    "SHIP_PORT_START": "port_start",
    "SHIP_PORT_END": "port_end",
    "SHIP_RETAIN_RELEASES": "retain_releases",
}
INT_FIELDS = {"port_start", "port_end", "retain_releases"}


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("SHIP_CONFIG", "~/.config/ship/config.toml")).expanduser()


def load_config(
    *,
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, object | None] | None = None,
) -> Config:
    env = os.environ if environ is None else environ
    values: dict[str, object] = asdict(Config())
    selected = path or config_path(env)
    if selected.exists():
        with selected.open("rb") as handle:
            parsed = tomllib.load(handle)
        unknown = set(parsed) - set(values)
        if unknown:
            raise ValidationError(f"unknown config key(s): {', '.join(sorted(unknown))}")
        values.update(parsed)
    for env_key, field in ENV_KEYS.items():
        if env_key in env:
            raw: object = env[env_key]
            if field in INT_FIELDS:
                try:
                    raw = int(str(raw))
                except ValueError as exc:
                    raise ValidationError(f"{env_key} must be an integer") from exc
            values[field] = raw
    if overrides:
        values.update({key: value for key, value in overrides.items() if value is not None})
    try:
        cfg = Config(**values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValidationError(f"invalid configuration: {exc}") from exc
    _validate_config(cfg)
    return cfg


def _validate_config(cfg: Config) -> None:
    if (
        not cfg.remote_root.startswith("/")
        or ".." in Path(cfg.remote_root).parts
        or not re.fullmatch(r"/[A-Za-z0-9._/-]+", cfg.remote_root)
    ):
        raise ValidationError("remote_root must be a safe absolute path without '..'")
    try:
        ipaddress.IPv4Address(cfg.server_ipv4)
    except ipaddress.AddressValueError as exc:
        raise ValidationError("server_ipv4 must be a valid IPv4 address") from exc
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", cfg.base_domain):
        raise ValidationError("base_domain must be a lowercase ASCII DNS name")
    if not (1024 <= cfg.port_start <= cfg.port_end <= 65535):
        raise ValidationError("port range must be between 1024 and 65535")
    if cfg.retain_releases < 1:
        raise ValidationError("retain_releases must be at least 1")


def render_config(cfg: Config) -> str:
    fields = asdict(cfg)
    lines = []
    for key, value in fields.items():
        rendered = f'"{value}"' if isinstance(value, str) else str(value)
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"
