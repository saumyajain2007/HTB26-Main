"""A real browser session over a small allowlist, with recording and offline replay.

Genuine browser use: Playwright drives Chromium and the page is parsed by the browser, not
fetched as JSON. The same code path runs live and offline, because replay serves recorded
response bodies through Playwright's own routing rather than taking a shortcut around the
browser. An offline demo that went down a different path would not demonstrate the live one.

Three things this module is responsible for:

``ALLOWED`` hosts only. Anything else is aborted, live or replayed. The agent cannot be
walked off PubMed and ClinicalTrials.gov by a link, a redirect or an injected instruction,
because the block is in the route handler and not in the model's judgement.

**Replay never reaches the network.** In ``replay`` mode every request is served from the
cache and a cache miss is an error. A demo that quietly fell back to the network would not
be an offline demo, and one that quietly returned an empty page would invent a result.

**Every step is timed and attributed.** ``StepLog`` records the action, the URL, the model,
its token usage and the elapsed seconds, which is what the on-screen figures come from.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED = ("pubmed.ncbi.nlm.nih.gov", "clinicaltrials.gov", "www.clinicaltrials.gov")

LIVE, RECORD, REPLAY = "live", "record", "replay"


class SessionError(RuntimeError):
    """The browser could not be driven as asked. Never a partial or invented page."""


def host_allowed(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host in ALLOWED


def cache_key(url: str) -> str:
    """Stable per-URL name, so a recorded run replays byte for byte."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


@dataclass
class Step:
    n: int
    action: str
    url: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    note: str = ""

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class StepLog:
    """What the run did, with the figures the task requires on screen."""

    steps: list = field(default_factory=list)

    def add(self, action: str, **kw) -> Step:
        step = Step(n=len(self.steps) + 1, action=action, **kw)
        self.steps.append(step)
        return step

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens for s in self.steps)

    @property
    def total_seconds(self) -> float:
        return round(sum(s.seconds for s in self.steps), 3)

    def models(self) -> list:
        return sorted({s.model for s in self.steps if s.model})

    def render(self) -> str:
        """The per-step table. Shown on screen during the run and kept in the output."""
        lines = [f"{'#':>3}  {'action':22} {'model':22} {'tok':>7} {'s':>7}  url", "-" * 100]
        for s in self.steps:
            lines.append(f"{s.n:>3}  {s.action:22} {(s.model or '-'):22} "
                         f"{s.tokens:>7} {s.seconds:>7.2f}  {(s.url or '')[:40]}")
        lines.append("-" * 100)
        lines.append(f"{len(self.steps)} steps, {self.total_tokens} tokens, "
                     f"{self.total_seconds:.2f}s, models: {', '.join(self.models()) or 'none'}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "steps": [asdict(s) for s in self.steps],
            "total_tokens": self.total_tokens,
            "total_seconds": self.total_seconds,
            "models": self.models(),
        }


class Session:
    """A Chromium session restricted to the allowlist, recording or replaying.

    Used as a context manager. ``mode`` is live, record or replay; record writes each page's
    HTML into ``cache_dir`` and replay serves it back with the network blocked.
    """

    def __init__(self, cache_dir, mode: str = REPLAY, *, log: StepLog | None = None,
                 timeout_ms: int = 30000):
        if mode not in (LIVE, RECORD, REPLAY):
            raise SessionError(f"mode {mode!r} is not one of {LIVE}, {RECORD}, {REPLAY}")
        self.cache_dir = Path(cache_dir)
        self.mode = mode
        self.log = log if log is not None else StepLog()
        self.timeout_ms = timeout_ms
        self.blocked: list = []
        self._play = self._browser = self._page = None

    # ---------------------------------------------------------------- lifecycle

    def __enter__(self) -> "Session":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise SessionError("playwright is not installed: pip install playwright "
                               "&& playwright install chromium") from exc
        if self.mode == REPLAY and not self.cache_dir.is_dir():
            raise SessionError(f"replay needs a recorded run in {self.cache_dir}; "
                               "record one with --mode record")
        self._play = sync_playwright().start()
        self._browser = self._play.chromium.launch()
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        self._page.route("**/*", self._route)
        return self

    def __exit__(self, *exc) -> None:
        for closer in (getattr(self._browser, "close", None), getattr(self._play, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:  # pragma: no cover - teardown must not mask a real error
                pass

    # ---------------------------------------------------------------- routing

    def _cached(self, url: str) -> Path:
        return self.cache_dir / f"{cache_key(url)}.json"

    def _route(self, route, request):
        """Every request passes through here, which is where the allowlist is enforced."""
        url = request.url
        if not host_allowed(url):
            self.blocked.append(url)
            route.abort()
            return
        if self.mode == REPLAY:
            path = self._cached(url)
            if not path.exists():
                # Never fall back to the network and never serve an empty page: either would
                # turn a missing recording into a silent "no record found".
                self.blocked.append(url)
                route.abort()
                return
            saved = json.loads(path.read_text(encoding="utf-8"))
            route.fulfill(status=saved.get("status", 200), body=saved["body"],
                          headers={"content-type": saved.get("content_type", "text/html")})
            return
        route.continue_()

    # ---------------------------------------------------------------- actions

    def open(self, url: str, *, note: str = "") -> str:
        """Navigate and return the page's visible text. Records the page in record mode."""
        if not host_allowed(url):
            self.log.add("blocked", url=url, note="host is not on the allowlist")
            raise SessionError(f"{url} is not on the allowlist {ALLOWED}")
        started = time.monotonic()
        try:
            response = self._page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            self.log.add("open_failed", url=url, seconds=round(time.monotonic() - started, 3),
                         note=type(exc).__name__)
            raise SessionError(f"could not open {url}: {type(exc).__name__}") from exc
        status = response.status if response is not None else 0
        text = self._page.inner_text("body")
        if self.mode == RECORD:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cached(url).write_text(json.dumps({
                "url": url, "status": status, "content_type": "text/html",
                "body": self._page.content(),
            }, indent=2) + "\n", encoding="utf-8", newline="\n")
        self.log.add("open", url=url, seconds=round(time.monotonic() - started, 3),
                     note=note or f"HTTP {status}, {len(text)} chars")
        return text

    def set_page(self, html: str, *, note: str = "fixture") -> str:
        """Load HTML directly. For tests and for checking the agent against a planted page."""
        started = time.monotonic()
        self._page.set_content(html)
        text = self._page.inner_text("body")
        self.log.add("set_page", seconds=round(time.monotonic() - started, 3), note=note)
        return text

    def recorded_urls(self) -> list:
        if not self.cache_dir.is_dir():
            return []
        out = []
        for path in sorted(self.cache_dir.glob("*.json")):
            try:
                out.append(json.loads(path.read_text(encoding="utf-8"))["url"])
            except (OSError, ValueError, KeyError):
                continue
        return out
