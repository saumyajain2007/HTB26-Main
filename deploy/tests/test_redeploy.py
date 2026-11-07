"""Exercise the real deploy script with command doubles, without touching a live stack."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "redeploy.sh"
SHA = "a" * 40


@pytest.mark.parametrize("failure", ["build", "migration"])
def test_failed_preparation_never_restarts_the_stack(tmp_path: Path, failure: str) -> None:
    (tmp_path / "deploy").mkdir()
    (tmp_path / "app/web").mkdir(parents=True)
    shutil.copyfile(SCRIPT, tmp_path / "deploy/redeploy.sh")
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "commands.log"
    for command in ("git", "uv", "npm", "pkill", "setsid"):
        stub = commands / command
        stub.write_text(
            '#!/bin/bash\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$COMMAND_LOG"\n'
            'if [[ "${0##*/}" == uv && "$*" == *deploy/db/migrate.py* '
            '&& "$FAILURE" == migration ]]; then exit 42; fi\n'
            'if [[ "${0##*/}" == npm && "$*" == *build* '
            '&& "$FAILURE" == build ]]; then exit 43; fi\n'
        )
        stub.chmod(0o755)
    result = subprocess.run(
        ["bash", str(tmp_path / "deploy/redeploy.sh"), SHA],
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "COMMAND_LOG": str(log),
            "DEPLOY_LOG_DIR": str(tmp_path),
            "FAILURE": failure,
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (42 if failure == "migration" else 43), result.stderr
    calls = log.read_text()
    assert f"git checkout -q --detach --force {SHA}" in calls
    assert "uv sync --all-packages --frozen --quiet" in calls
    assert "pkill" not in calls
    assert "setsid" not in calls
    if failure == "build":
        assert "deploy/db/migrate.py" not in calls
