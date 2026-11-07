"""Concurrent experiments must publish complete evidence cache entries safely."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import httpx
import pytest

from pipeline.packets import EvidenceSources


def test_concurrent_evidence_requests_publish_the_same_cache_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = Barrier(2, timeout=5)
    replace = Path.replace

    def replace_together(source: Path, target: Path) -> Path:
        published.wait()
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", replace_together)
    expected = {"data": {"id": "shared-evidence"}}
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=expected))
    ) as client:
        sources = [EvidenceSources(str(tmp_path), client=client) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda source: source.request("https://example.test/evidence", "release-1"),
                sources,
            ))
    assert results == [expected, expected]
    assert EvidenceSources(str(tmp_path), offline=True).request(
        "https://example.test/evidence", "release-1"
    ) == expected
    assert len(list(tmp_path.rglob("*.json"))) == 1
    assert not list(tmp_path.rglob("*.tmp"))
