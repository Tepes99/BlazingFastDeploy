# FastAPI and DuckDB

Run a DuckDB-backed application with one Uvicorn worker and store the database at `/data/app.duckdb`. The production directory `/srv/ship/apps/<name>/data` is mounted at `/data` and survives deployments and default removal.

Candidate health checks use a fresh temporary directory. They never mount the production database. Only one writable production container runs against persistent DuckDB data, and local `*.duckdb` files are excluded from rsync and Docker build contexts.

Code rollback may be unsafe after a schema migration. Make migration steps backward-compatible and back up the data directory before risky schema changes. PostgreSQL becomes a better choice when the application needs concurrent writers, several application instances, independent database operations, or stronger online migration and backup tooling. PostgreSQL is outside version one.

