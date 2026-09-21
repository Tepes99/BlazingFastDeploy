# ship

`ship` publishes small web applications from an Apple Silicon Mac to one existing x86_64 Hetzner VPS. It transfers source over SSH, builds the image on the VPS, checks a disposable candidate, and runs the production container behind host-installed Caddy.

The first version intentionally supports one server and one operator. It does not provision infrastructure, modify DNS, push images to a registry, or promise zero downtime.

## Install and test

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy src
uv tool install .
ship --help
```

During development, use `uv run ship`. A completely local preview reads and validates the application but makes no SSH connection:

```bash
cd examples/fastapi-duckdb
uv run --project ../.. ship deploy --dry-run
```

## Normal workflow

```bash
cd my-fastapi-app
ship init --name my-fastapi-app --example fastapi
ship check
ship deploy
```

The commands are `init`, `bootstrap`, `check`, `deploy`, `list`, `status [app]`, `logs <app>`, `restart <app>`, and `remove <app>`. Mutating commands support `--dry-run`; machine-oriented commands support `--json`. JSON never includes environment values.

Before the first live deployment, configure the wildcard DNS record described in [docs/dns.md](docs/dns.md), review [docs/bootstrap.md](docs/bootstrap.md), and explicitly run:

```bash
ship bootstrap --dry-run
ship bootstrap
```

The live command changes the existing server. This repository and its tests never invoke it automatically.

See [the first deployment guide](docs/first-deployment.md), [application contract](docs/application-contract.md), and [security model](docs/security.md).

