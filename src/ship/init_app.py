from __future__ import annotations

from pathlib import Path

from .errors import ShipError
from .manifest import derive_domain, validate_name

DOCKERIGNORE = """.git
.venv
__pycache__
.pytest_cache
.mypy_cache
.ruff_cache
node_modules
dist
build
*.duckdb
*.duckdb.wal
.env
.env.*
!.env.production.example
data
"""

DOCKERFILE = """FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev
COPY . .
ENV PATH=/app/.venv/bin:$PATH
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
"""

FASTAPI_APP = """from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def index() -> dict[str, str]:
    return {"message": "Hello from ship"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
"""

FASTAPI_PROJECT = """[project]
name = "ship-fastapi-example"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.115", "uvicorn>=0.34", "duckdb>=1.2"]
"""


def generated_files(root: Path, name: str, base_domain: str, example: bool) -> dict[Path, str]:
    validate_name(name)
    domain = derive_domain(name, base_domain)
    manifest = f'''version = 1
name = "{name}"
domain = "{domain}"

[service]
container_port = 8000
healthcheck = "/health"
memory = "384m"
cpus = 0.5

[data]
enabled = true
container_path = "/data"

[environment]
file = ".env.production"
'''
    result = {
        root / "ship.toml": manifest,
        root / ".dockerignore": DOCKERIGNORE,
        root / ".env.production.example": "# Copy to .env.production and add production values.\n",
        root / "Dockerfile": DOCKERFILE,
    }
    if example:
        result[root / "app.py"] = FASTAPI_APP
        result[root / "pyproject.toml"] = FASTAPI_PROJECT
        result[root / ".env.production"] = "# Production values; never commit this file.\n"
    return result


def initialize(
    root: Path, name: str, base_domain: str, *, example: bool, overwrite: bool
) -> list[str]:
    files = generated_files(root, name, base_domain, example)
    existing = [path for path in files if path.exists()]
    if existing and not overwrite:
        raise ShipError(
            "refusing to overwrite existing files: " + ", ".join(path.name for path in existing)
        )
    root.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        if not path.exists() or overwrite:
            path.write_text(content)
    return [str(path) for path in files]
