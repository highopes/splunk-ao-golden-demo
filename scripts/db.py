#!/usr/bin/env python3
"""Manage this project's native macOS PostgreSQL cluster; never a global service."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".runtime/postgres"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    args = parser.parse_args()
    candidates = [Path("/opt/homebrew/opt/postgresql@17/bin"), Path("/usr/local/opt/postgresql@17/bin")]
    pg_dir = next((p for p in candidates if (p / "pg_ctl").is_file()), None)
    if pg_dir is None:
        raise SystemExit("Install native prerequisites: brew install postgresql@17 pgvector")
    if args.action in ("stop", "status"):
        if not (DATA / "PG_VERSION").exists():
            raise SystemExit("This project's database has not been initialized")
        command = [str(pg_dir / "pg_ctl"), "-D", str(DATA), args.action]
        if args.action == "stop":
            command += ["-m", "fast", "-w"]
        raise SystemExit(subprocess.call(command))

    secrets_file = ROOT / ".streamlit/secrets.toml"
    if not secrets_file.exists():
        raise SystemExit("Copy .streamlit/secrets.toml.example to .streamlit/secrets.toml first")
    with secrets_file.open("rb") as handle:
        config = tomllib.load(handle)
    if config.get("postgres_host", "localhost") not in ("localhost", "127.0.0.1"):
        raise SystemExit("This helper manages a local database; postgres_host must be localhost")
    password = config.get("postgres_password", "")
    if not password or password.startswith("YOUR_") or "\n" in password:
        raise SystemExit("Set a local postgres_password before starting")
    user = config.get("postgres_user", "postgres")
    database = config.get("postgres_db", "vectordb")
    port = int(config.get("postgres_port", 5432))
    if not 1 <= port <= 65535:
        raise SystemExit("Invalid postgres_port")
    DATA.parent.mkdir(parents=True, exist_ok=True)
    # Short socket path: project paths under OneDrive can exceed macOS's limit.
    socket_dir = Path(tempfile.gettempdir()) / f"splunk-ao-pg-{os.getuid()}"
    socket_dir.mkdir(mode=0o700, exist_ok=True)
    if not (DATA / "PG_VERSION").exists():
        with tempfile.NamedTemporaryFile(mode="w") as pwfile:
            pwfile.write(password + "\n")
            pwfile.flush()
            subprocess.run([
                str(pg_dir / "initdb"), "-D", str(DATA), "-U", user,
                "--auth-local=trust", "--auth-host=scram-sha-256",
                "--encoding=UTF8", "--locale=C", f"--pwfile={pwfile.name}",
            ], check=True)
    running = subprocess.run([str(pg_dir / "pg_ctl"), "-D", str(DATA), "status"], capture_output=True).returncode == 0
    if not running:
        subprocess.run([
            str(pg_dir / "pg_ctl"), "-D", str(DATA), "-l", str(DATA.parent / "postgres.log"),
            "-o", f"-h 127.0.0.1 -p {port} -k {socket_dir}", "-w", "start",
        ], check=True)
    import psycopg
    from psycopg import sql
    with psycopg.connect(host="127.0.0.1", port=port, user=user, password=password, dbname="postgres", autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    with psycopg.connect(host="127.0.0.1", port=port, user=user, password=password, dbname=database, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        version = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]
    print(f"Local PostgreSQL ready at 127.0.0.1:{port}; database={database}; pgvector={version}")


if __name__ == "__main__":
    main()
