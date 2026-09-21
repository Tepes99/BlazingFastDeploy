# First deployment

Install the CLI and preview the server setup:

```bash
uv tool install .
ship bootstrap --dry-run
```

After reviewing the output and deciding to change the real server, run `ship bootstrap`. Configure the wildcard Route 53 record in [dns.md](dns.md), then verify the platform:

```bash
ship check
```

Deploy the included example:

```bash
cd examples/fastapi-duckdb
uv lock
ship deploy --dry-run
ship deploy
ship status ship-example
ship logs ship-example
```

The image builds on the x86 VPS, avoiding accidental Apple Silicon production images. A healthy result is served at `https://ship-example.apps.teemusaha.com`.
