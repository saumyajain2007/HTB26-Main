"""Throwaway Postgres for the migration tests. Never points at Tiger.

Set TEST_DATABASE_URL to an admin connection on a disposable server (each test
creates and drops its own database there). Without it, a temporary cluster is
started with the local initdb/pg_ctl binaries. The helpers live in
`db/throwaway_pg.py`, which the API tests share.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import throwaway_pg


@pytest.fixture(scope="session")
def admin_conninfo() -> Iterator[str]:
    with throwaway_pg.admin_conninfo() as admin:
        if admin is None:
            pytest.skip(
                "set TEST_DATABASE_URL or install Postgres (initdb, pg_ctl) to run database tests"
            )
        yield admin


@pytest.fixture
def database(admin_conninfo: str) -> Iterator[str]:
    """A fresh, empty database for one test."""
    with throwaway_pg.fresh_database(admin_conninfo) as conninfo:
        yield conninfo
