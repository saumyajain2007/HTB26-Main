"""A failed or corrupted release download must never become the installed archive."""

import hashlib
import io
from pathlib import Path

import pytest

from deploy.ci.install_lean import download_verified


def test_only_publish_verified_release_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"test archive bytes"
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(content)
    )
    target = tmp_path / "lean.tar.zst"
    download_verified(
        "https://api.github.com/test", target, hashlib.sha256(content).hexdigest()
    )
    assert target.read_bytes() == content


def test_reject_corruption_without_replacing_existing_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(b"corrupt")
    )
    target = tmp_path / "lean.tar.zst"
    target.write_bytes(b"previously verified")
    with pytest.raises(ValueError, match="checksum mismatch"):
        download_verified("https://api.github.com/test", target, "0" * 64)
    assert target.read_bytes() == b"previously verified"
    assert not target.with_suffix(".zst.partial").exists()
