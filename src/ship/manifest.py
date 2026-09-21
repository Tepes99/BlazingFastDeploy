from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import ValidationError

NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}\.?$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MEMORY_RE = re.compile(r"^[1-9][0-9]*(?:[kKmMgG])?$")


@dataclass(frozen=True)
class Service:
    container_port: int
    healthcheck: str = "/health"
    memory: str = "384m"
    cpus: float = 0.5


@dataclass(frozen=True)
class Data:
    enabled: bool = False
    container_path: str = "/data"


@dataclass(frozen=True)
class Manifest:
    version: int
    name: str
    domain: str
    service: Service
    data: Data
    environment_file: str | None = None


def derive_domain(name: str, base_domain: str) -> str:
    validate_name(name)
    validate_domain(base_domain)
    return f"{name}.{base_domain}"


def validate_name(name: str) -> None:
    if not NAME_RE.fullmatch(name) or len(name) > 48:
        raise ValidationError(
            "application name must be 1-48 lowercase letters, digits, or single hyphens, "
            "starting with a letter"
        )


def validate_domain(domain: str) -> None:
    if not DOMAIN_RE.fullmatch(domain) or any(
        part.startswith("xn--") for part in domain.split(".")
    ):
        raise ValidationError("domain must be a lowercase ASCII DNS name")


def validate_relative_file(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."} or "\\" in value:
        raise ValidationError(f"{label} must be a safe relative file path")


def validate_absolute_container_path(value: str) -> None:
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or value == "/":
        raise ValidationError("data.container_path must be an absolute container path below root")


def load_manifest(path: Path, base_domain: str) -> Manifest:
    if not path.exists():
        raise ValidationError(f"required file not found: {path}")
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    allowed = {"version", "name", "domain", "service", "data", "environment"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValidationError(f"unknown manifest key(s): {', '.join(sorted(unknown))}")
    version = raw.get("version")
    name = raw.get("name")
    if version != 1:
        raise ValidationError("ship.toml version must be 1")
    if not isinstance(name, str):
        raise ValidationError("name is required")
    validate_name(name)
    domain = raw.get("domain") or derive_domain(name, base_domain)
    if not isinstance(domain, str):
        raise ValidationError("domain must be a string")
    validate_domain(domain)
    if domain != derive_domain(name, base_domain):
        raise ValidationError(f"domain must be {derive_domain(name, base_domain)}")

    service_raw = raw.get("service")
    if not isinstance(service_raw, dict):
        raise ValidationError("[service] is required")
    if set(service_raw) - {"container_port", "healthcheck", "memory", "cpus"}:
        raise ValidationError("unknown key in [service]")
    port = service_raw.get("container_port")
    health = service_raw.get("healthcheck", "/health")
    memory = service_raw.get("memory", "384m")
    cpus = service_raw.get("cpus", 0.5)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValidationError("service.container_port must be an integer from 1 to 65535")
    if (
        not isinstance(health, str)
        or not health.startswith("/")
        or any(c.isspace() for c in health)
    ):
        raise ValidationError(
            "service.healthcheck must be an absolute HTTP path without whitespace"
        )
    if not isinstance(memory, str) or not MEMORY_RE.fullmatch(memory):
        raise ValidationError("service.memory must look like 384m or 1g")
    if not isinstance(cpus, (int, float)) or isinstance(cpus, bool) or not 0 < cpus <= 64:
        raise ValidationError("service.cpus must be greater than 0 and at most 64")

    data_raw = raw.get("data", {})
    if not isinstance(data_raw, dict) or set(data_raw) - {"enabled", "container_path"}:
        raise ValidationError("invalid [data] section")
    enabled = data_raw.get("enabled", False)
    container_path = data_raw.get("container_path", "/data")
    if not isinstance(enabled, bool) or not isinstance(container_path, str):
        raise ValidationError("data.enabled must be boolean and container_path must be a string")
    validate_absolute_container_path(container_path)

    environment_raw = raw.get("environment")
    environment_file: str | None = None
    if environment_raw is not None:
        if not isinstance(environment_raw, dict) or set(environment_raw) != {"file"}:
            raise ValidationError("[environment] must contain only file")
        environment_file = environment_raw["file"]
        if not isinstance(environment_file, str):
            raise ValidationError("environment.file must be a string")
        validate_relative_file(environment_file, "environment.file")

    return Manifest(
        version=version,
        name=name,
        domain=domain,
        service=Service(port, health, memory, float(cpus)),
        data=Data(enabled, container_path),
        environment_file=environment_file,
    )


def validate_application(root: Path, base_domain: str) -> Manifest:
    manifest = load_manifest(root / "ship.toml", base_domain)
    if not (root / "Dockerfile").is_file():
        raise ValidationError("required file not found: Dockerfile")
    if manifest.environment_file and not (root / manifest.environment_file).is_file():
        raise ValidationError(f"environment file not found: {manifest.environment_file}")
    return manifest
