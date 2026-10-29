"""Pull the one-row-per-trial table from AACT.

Two ways in, same SQL:
  1. Live AACT Postgres (needs a free account; creds in .env).
  2. AACT static "flat files" download (pipe-delimited .txt per table), queried with DuckDB.
     Download: https://aact.ctti-clinicaltrials.org/downloads -> unzip into data/raw/aact/

Usage:
    python -m dtp.ingest.aact --source postgres
    python -m dtp.ingest.aact --source flatfiles --dir data/raw/aact
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from dtp import config


def load_sql(name: str = "trials.sql") -> str:
    sql = (config.SQL_DIR / name).read_text()
    return sql.format(start_min=config.START_MIN, start_max=config.START_MAX)


def from_postgres(sql: str | None = None) -> pd.DataFrame:
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text

    load_dotenv(config.ROOT / ".env")
    url = (
        f"postgresql+psycopg2://{os.environ['AACT_USER']}:{os.environ['AACT_PASSWORD']}"
        f"@{os.getenv('AACT_HOST', 'aact-db.ctti-clinicaltrials.org')}:{os.getenv('AACT_PORT', '5432')}"
        f"/{os.getenv('AACT_DB', 'aact')}"
    )
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("SET search_path TO ctgov"))
        return pd.read_sql(text(sql or load_sql()), conn)


def duckdb_with_flatfiles(flat_dir: Path):
    """DuckDB connection with one view per AACT table found in flat_dir."""
    import duckdb

    con = duckdb.connect()
    for table in config.AACT_TABLES:
        path = Path(flat_dir) / f"{table}.txt"
        if not path.exists():
            raise FileNotFoundError(f"Missing AACT flat file: {path}")
        con.execute(
            f"CREATE VIEW {table} AS SELECT * FROM read_csv('{path.as_posix()}', "
            "delim='|', header=true, quote='\"', escape='\"', sample_size=-1)"
        )
    return con


def from_flatfiles(flat_dir: Path, sql: str | None = None) -> pd.DataFrame:
    con = duckdb_with_flatfiles(flat_dir)
    return con.execute(sql or load_sql()).df()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["postgres", "flatfiles"], required=True)
    ap.add_argument("--dir", type=Path, default=config.RAW / "aact")
    ap.add_argument("--out", type=Path, default=config.INTERIM / "trials_raw.parquet")
    args = ap.parse_args()

    df = from_postgres() if args.source == "postgres" else from_flatfiles(args.dir)
    df.to_parquet(args.out, index=False)
    print(f"wrote {len(df):,} trials -> {args.out}")
    print(df["overall_status"].value_counts().to_string())


if __name__ == "__main__":
    main()
