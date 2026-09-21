from __future__ import annotations

from .manifest import Manifest


def fragment(domain: str, port: int) -> str:
    return f"{domain} {{\n    reverse_proxy 127.0.0.1:{port}\n}}\n"


def fragment_for(manifest: Manifest, port: int) -> str:
    return fragment(manifest.domain, port)


def atomic_caddy_commands(app: str, content_path: str) -> list[list[str]]:
    """Commands used by the privileged helper after validating app/content inputs."""
    candidate = f"/etc/caddy/apps/.{app}.caddy.candidate"
    final = f"/etc/caddy/apps/{app}.caddy"
    return [
        ["install", "-o", "root", "-g", "root", "-m", "0644", content_path, candidate],
        ["caddy", "validate", "--config", "/etc/caddy/Caddyfile"],
        ["mv", "--", candidate, final],
        ["systemctl", "reload", "caddy"],
    ]
