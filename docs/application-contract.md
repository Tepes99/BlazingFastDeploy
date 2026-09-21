# Application contract

Every application needs a `Dockerfile` and `ship.toml`:

```toml
version = 1
name = "medicine"
domain = "medicine.apps.teemusaha.com"

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
```

The environment section is optional. Names are lowercase ASCII letters, digits, and single hyphens, start with a letter, and are at most 48 characters. The domain must equal `<name>.apps.teemusaha.com`. Paths cannot be absolute or traverse upward. `ship` also validates ports, health paths, memory, CPU, and data paths.

Source is copied to `/srv/ship/releases/<name>/<release-id>`. Git data, virtual environments, caches, build output, environment files, `data`, and DuckDB files are excluded. A declared environment file is uploaded separately to `/srv/ship/apps/<name>/secrets/environment` with mode `0600` and passed with Docker's `--env-file`. Its values are never emitted in JSON or logs. If Git tracks it, `ship check` and `ship deploy` warn; remove it with `git rm --cached` and add it to `.gitignore`.

Production is named `ship-<name>` and bound only to `127.0.0.1`. The latest three releases and their image tags are retained. Persistent data and secrets live outside releases.

