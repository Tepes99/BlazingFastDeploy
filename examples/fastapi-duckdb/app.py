from pathlib import Path

import duckdb
from fastapi import FastAPI

app = FastAPI()
database = Path("/data/app.duckdb")


@app.get("/")
def index() -> dict[str, int]:
    database.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS visits (visited_at TIMESTAMP DEFAULT now())")
        connection.execute("INSERT INTO visits DEFAULT VALUES")
        count = connection.execute("SELECT count(*) FROM visits").fetchone()[0]
    return {"visits": int(count)}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
