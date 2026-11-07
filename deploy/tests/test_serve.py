"""Check production launch arguments without running servers or using credentials."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "serve.sh"


@pytest.mark.parametrize(
    ("codespaces", "override", "expected"),
    [("false", "", "false"), ("true", "", "true"), ("true", "false", "false")],
)
def test_launch_bounds_connections_and_sets_cookie_security(
    tmp_path: Path, codespaces: str, override: str, expected: str
) -> None:
    (tmp_path / "deploy").mkdir()
    shutil.copyfile(SCRIPT, tmp_path / "deploy/serve.sh")
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "commands.log"
    uv = commands / "uv"
    uv.write_text(
        '#!/bin/bash\nprintf "%s cookie=%s\\n" "$*" '
        '"$OXHACK_SESSION_COOKIE_SECURE" >> "$COMMAND_LOG"\n'
    )
    uv.chmod(0o755)
    result = subprocess.run(
        ["bash", str(tmp_path / "deploy/serve.sh")],
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "COMMAND_LOG": str(log),
            "DATABASE_URL": "postgresql://unused",
            "OXHACK_DOCKING": "fixture",
            "CODESPACES": codespaces,
            "OXHACK_SESSION_COOKIE_SECURE": override,
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert "sync --all-packages --frozen --quiet" in calls
    api = next(line for line in calls.splitlines() if "uvicorn" in line)
    assert f"cookie={expected}" in api
    assert "--limit-concurrency 64 --backlog 128 --timeout-keep-alive 5" in api
    assert "--timeout-graceful-shutdown 15 --forwarded-allow-ips 127.0.0.1" in api
