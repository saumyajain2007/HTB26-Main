# /// script
# requires-python = ">=3.11"
# dependencies = ["psycopg[binary]>=3.2,<4"]
# ///
"""Apply db/migrations/*.sql in order and record each one in schema_migrations.

Usage:
    uv run db/migrate.py                 # uses $DATABASE_URL
    uv run db/migrate.py --database-url postgresql://...
    uv run db/migrate.py --dry-run       # list pending files, change nothing

Each file runs in its own transaction, under an advisory lock so two runs can't
interleave. A recorded file whose contents changed is an error: write a new
numbered file instead of editing an applied one.

Databases created before this script existed already hold 0001 (the Tiger
service does). If schema_migrations is empty but the 0001 tables exist, 0001 is
recorded as applied without running it again.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
FILE_PATTERN = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
# Arbitrary constant shared by every run of this script.
LOCK_KEY = 0x0A11_C0DE
BASELINE_VERSION = "0001"


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = FILE_PATTERN.match(path.name)
        if not match:
            raise SystemExit(
                f"Unexpected migration file name: {path.name} (want NNNN_name.sql)"
            )
        migrations.append(Migration(match.group(1), path, path.read_text()))
    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise SystemExit(f"Duplicate migration numbers in {directory}")
    return migrations


def migrate(
    conninfo: str, *, dry_run: bool = False, directory: Path = MIGRATIONS_DIR
) -> list[str]:
    """Apply pending migrations. Returns the versions applied (or pending, on a dry run)."""
    migrations = load_migrations(directory)
    done: list[str] = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        # Held for the whole run, before anything is read or created, so
        # concurrent runs queue up instead of racing.
        conn.execute("select pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            has_table = conn.execute(
                "select to_regclass('public.schema_migrations') is not null"
            ).fetchone()[0]
            if not has_table and not dry_run:
                conn.execute(
                    """
                    create table schema_migrations (
                      version    text primary key,
                      filename   text not null,
                      checksum   text not null,
                      applied_at timestamptz not null default now()
                    )
                    """
                )
                has_table = True
            applied = (
                dict(
                    conn.execute(
                        "select version, checksum from schema_migrations"
                    ).fetchall()
                )
                if has_table
                else {}
            )
            _baseline(conn, migrations, applied, dry_run)

            for migration in migrations:
                if migration.version in applied:
                    if applied[migration.version] != migration.checksum:
                        raise SystemExit(
                            f"{migration.path.name} changed after it was applied. "
                            "Add a new numbered migration instead of editing this one."
                        )
                    continue
                done.append(migration.version)
                if dry_run:
                    continue
                with conn.transaction():
                    conn.execute(migration.sql)
                    conn.execute(
                        "insert into schema_migrations (version, filename, checksum) values (%s, %s, %s)",
                        (migration.version, migration.path.name, migration.checksum),
                    )
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))
    return done


def _baseline(
    conn: psycopg.Connection,
    migrations: list[Migration],
    applied: dict[str, str],
    dry_run: bool,
) -> None:
    """Record 0001 as applied on databases that got it before schema_migrations existed."""
    if applied:
        return
    already = conn.execute(
        "select to_regclass('public.experiments') is not null"
    ).fetchone()[0]
    if not already:
        return
    baseline = next((m for m in migrations if m.version == BASELINE_VERSION), None)
    if baseline is None:
        return
    print(
        f"Found existing {BASELINE_VERSION} tables; recording {baseline.path.name} as applied."
    )
    applied[baseline.version] = baseline.checksum
    if not dry_run:
        conn.execute(
            "insert into schema_migrations (version, filename, checksum) values (%s, %s, %s)",
            (baseline.version, baseline.path.name, baseline.checksum),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list pending migrations and change nothing",
    )
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("set DATABASE_URL or pass --database-url")
    versions = migrate(args.database_url, dry_run=args.dry_run)
    verb = "Pending" if args.dry_run else "Applied"
    print(f"{verb}: {', '.join(versions)}" if versions else "Up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
