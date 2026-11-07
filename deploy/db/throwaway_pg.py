"""Throwaway Postgres for tests. Never points at Tiger or any remote server.

Shared by `db/tests` and `api/tests` (both put this folder on `sys.path`):

- `admin_conninfo()` yields an admin connection string. With
  `TEST_DATABASE_URL` set it uses that disposable server; otherwise it starts a
  temporary cluster with the local `initdb` and `pg_ctl` and removes it after.
  It yields None when neither is available, so callers can skip.
- `create_database()` and `drop_database()` make and remove one database
  there, optionally cloned from a template (much faster than migrating again).

Plain context managers, no pytest, so each test tree wraps them in its own
fixtures.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ENV_VAR = "TEST_DATABASE_URL"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def admin_conninfo() -> Iterator[str | None]:
    """An admin connection to a disposable server, or None if there is none."""
    url = os.environ.get(ENV_VAR)
    if url:
        yield url
        return
    if not (shutil.which("initdb") and shutil.which("pg_ctl")):
        yield None
        return
    root = Path(tempfile.mkdtemp(prefix="oxhack-pg-"))
    data, port = root / "data", _free_port()
    subprocess.run(
        ["initdb", "-D", str(data), "-U", "postgres", "-A", "trust"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "pg_ctl",
            "-D",
            str(data),
            # Unix socket only, in the temporary folder: nothing listens on TCP.
            "-o",
            f"-p {port} -k {root} -c listen_addresses='' -c fsync=off",
            "-l",
            str(root / "log"),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:
        yield make_conninfo(
            host=str(root), port=port, user="postgres", dbname="postgres"
        )
    finally:
        subprocess.run(
            ["pg_ctl", "-D", str(data), "-m", "immediate", "stop"],
            check=False,
            capture_output=True,
        )
        shutil.rmtree(root, ignore_errors=True)


def create_database(
    admin: str, *, template: str | None = None, prefix: str = "oxhack_test"
) -> str:
    """Create an empty (or template-cloned) database; return its connection string."""
    name = f"{prefix}_{uuid.uuid4().hex[:12]}"
    statement = sql.SQL("create database {}").format(sql.Identifier(name))
    if template is not None:
        statement += sql.SQL(" template {}").format(sql.Identifier(template))
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(statement)
    return database_conninfo(admin, name)


def database_conninfo(admin: str, name: str) -> str:
    params = conninfo_to_dict(admin)
    params["dbname"] = name
    return make_conninfo(**params)


def database_name(conninfo: str) -> str:
    return str(conninfo_to_dict(conninfo)["dbname"])


def drop_database(admin: str, conninfo: str) -> None:
    statement = sql.SQL("drop database if exists {} with (force)").format(
        sql.Identifier(database_name(conninfo))
    )
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(statement)


@contextmanager
def fresh_database(admin: str, *, template: str | None = None) -> Iterator[str]:
    """A database for one test, dropped afterwards."""
    conninfo = create_database(admin, template=template)
    try:
        yield conninfo
    finally:
        drop_database(admin, conninfo)
