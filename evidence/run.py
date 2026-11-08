"""Run the browser verification over the top candidates and write a checkable record.

For each candidate the agent opens a PubMed search and a ClinicalTrials.gov search in a real
browser, reads the visible text, and asks the model the three questions. Each answer must
carry a quote that is on the page or it is dropped, and any question the page does not answer
is recorded as ``no record found``.

The model is a callable, as the jury's ``model_call`` and the ranker's ``smoke`` are, so the
same loop runs with a live provider, with a recorded transcript, or with a stub in tests.
That is also what makes the offline demo faithful: replay drives the same browser over
recorded pages with recorded replies, rather than a second code path that only looks similar.

    python -m evidence.run --result RESULT.json --mode record --cache data/evidence/run1
    python -m evidence.run --result RESULT.json --mode replay --cache data/evidence/run1
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from .extract import (QUESTIONS, ExtractionError, accept, build_prompt, fill_unanswered,
                      find_injections, new_nonce, parse_reply)
from .session import REPLAY, Session, SessionError, StepLog

PUBMED = "https://pubmed.ncbi.nlm.nih.gov/?term={term}"
CLINICALTRIALS = "https://clinicaltrials.gov/search?term={term}"
TOP_N = 10


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ModelError(RuntimeError):
    """The model could not be called. Never a substituted answer."""


class RecordedModel:
    """Replays model replies from a transcript, keyed by candidate and source.

    A miss is an error. Replay must not quietly produce an empty reply, because an empty
    reply becomes "no record found", which is a result the run never actually obtained.
    """

    def __init__(self, transcript: list):
        self._by_key = {}
        for entry in transcript:
            self._by_key[entry["key"]] = entry
        self.name = next((e.get("model", "recorded") for e in transcript), "recorded")

    @classmethod
    def from_file(cls, path) -> "RecordedModel":
        path = Path(path)
        if not path.exists():
            raise ModelError(f"{path} does not exist: replay needs the recorded transcript")
        return cls(json.loads(path.read_text(encoding="utf-8"))["replies"])

    def __call__(self, prompt: str, *, key: str) -> Reply:
        entry = self._by_key.get(key)
        if entry is None:
            raise ModelError(f"no recorded reply for {key!r}; re-record the run")
        return Reply(entry["text"], entry.get("model", self.name),
                     entry.get("prompt_tokens", 0), entry.get("completion_tokens", 0))


class Recorder:
    """Wraps a live model and keeps every reply so the run can be replayed offline."""

    def __init__(self, inner, name: str = "live"):
        self.inner = inner
        self.name = name
        self.replies: list = []

    def __call__(self, prompt: str, *, key: str) -> Reply:
        reply = self.inner(prompt, key=key)
        self.replies.append({"key": key, "model": reply.model, "text": reply.text,
                             "prompt_tokens": reply.prompt_tokens,
                             "completion_tokens": reply.completion_tokens})
        return reply

    def transcript(self) -> dict:
        return {"replies": self.replies}


def top_candidates(result: dict, n: int = TOP_N) -> list:
    """The top n ranked candidate names from an AntibioticCandidate result."""
    ranked = [c for c in result.get("candidates", []) if c.get("rank") is not None]
    return [c["name"] for c in sorted(ranked, key=lambda c: c["rank"])[:n]]


def search_urls(candidate: str) -> list:
    term = quote_plus(candidate)
    return [("pubmed", PUBMED.format(term=term)),
            ("clinicaltrials", CLINICALTRIALS.format(term=term))]


def verify_candidate(session: Session, model, candidate: str) -> dict:
    """One candidate: both sources, claims checked against the page."""
    claims, rejected, injections, errors = [], [], [], []
    for source, url in search_urls(candidate):
        try:
            page_text = session.open(url, note=f"{candidate} on {source}")
        except SessionError as exc:
            errors.append({"candidate": candidate, "source": source, "url": url,
                           "error": str(exc)})
            continue

        seen = find_injections(page_text)
        if seen:
            injections.append({"candidate": candidate, "source": source, "url": url,
                               "found": seen})
            session.log.add("injection_recorded", url=url,
                            note=f"{len(seen)} pattern(s) in page content; treated as data")

        key = f"{candidate}|{source}"
        prompt = build_prompt(candidate, page_text, url, source, new_nonce())
        started = time.monotonic()
        try:
            reply = model(prompt, key=key)
        except ModelError as exc:
            session.log.add("model_failed", url=url,
                            seconds=round(time.monotonic() - started, 3), note=str(exc)[:80])
            errors.append({"candidate": candidate, "source": source, "url": url,
                           "error": str(exc)})
            continue
        session.log.add("model", url=url, model=reply.model,
                        prompt_tokens=reply.prompt_tokens,
                        completion_tokens=reply.completion_tokens,
                        seconds=round(time.monotonic() - started, 3),
                        note=f"{candidate} / {source}")

        try:
            proposed = parse_reply(reply.text)
        except ExtractionError as exc:
            rejected.append({"candidate": candidate, "source": source, "url": url,
                             "reason": f"unusable reply: {exc}"})
            proposed = []
        good, bad = accept(proposed, candidate=candidate, page_text=page_text, url=url,
                           source=source)
        for item in bad:
            rejected.append({**item, "candidate": candidate, "source": source, "url": url})
        claims.extend(fill_unanswered(good, candidate=candidate, url=url, source=source))
    return {"candidate": candidate, "claims": claims, "rejected": rejected,
            "injections": injections, "errors": errors}


def run(candidates: list, cache_dir, model, *, mode: str = REPLAY) -> dict:
    log = StepLog()
    everything = {"claims": [], "rejected": [], "injections": [], "errors": []}
    with Session(cache_dir, mode=mode, log=log) as session:
        for candidate in candidates:
            found = verify_candidate(session, model, candidate)
            everything["claims"].extend(found["claims"])
            for bucket in ("rejected", "injections", "errors"):
                everything[bucket].extend(found[bucket])
        blocked = list(session.blocked)

    claims = everything["claims"]
    supported = [c for c in claims if not c.is_no_record]
    return {
        "mode": mode,
        "candidates": candidates,
        "questions": list(QUESTIONS),
        "claims": [c.as_dict() for c in claims],
        "counts": {
            "candidates": len(candidates),
            "claims": len(claims),
            "with_citation": len(supported),
            "no_record_found": len(claims) - len(supported),
            "rejected": len(everything["rejected"]),
            "injection_pages": len(everything["injections"]),
            "errors": len(everything["errors"]),
            "blocked_requests": len(blocked),
        },
        "rejected": everything["rejected"],
        "injections": everything["injections"],
        "errors": everything["errors"],
        "blocked_requests": blocked,
        "steps": log.as_dict(),
        "step_table": log.render(),
    }


def as_markdown(record: dict) -> str:
    counts = record["counts"]
    lines = [
        "# Browser verification of the top candidates",
        "",
        f"Mode: `{record['mode']}`. {counts['candidates']} candidates, "
        f"{counts['claims']} claims, {counts['with_citation']} with a citation, "
        f"{counts['no_record_found']} recorded as no record found.",
        "",
        "```",
        record["step_table"],
        "```",
        "",
        "## Claims",
        "",
        "Every claim below carries the URL it came from and the exact text on that page that",
        "supports it. A claim whose quote was not found on the page was dropped, not reported.",
        "",
    ]
    for candidate in record["candidates"]:
        mine = [c for c in record["claims"] if c["candidate"] == candidate]
        if not mine:
            continue
        lines.append(f"### {candidate}")
        lines.append("")
        for claim in mine:
            if claim["answer"].lower() == "no record found":
                lines.append(f"- **{claim['question']}** ({claim['source']}): no record found. "
                             f"<{claim['url']}>")
            else:
                lines.append(f"- **{claim['question']}** ({claim['source']}): {claim['answer']}")
                lines.append(f"  - quote: “{claim['quote']}”")
                lines.append(f"  - source: <{claim['url']}>")
        lines.append("")
    if record["rejected"]:
        lines += ["## Dropped claims", "",
                  "Recorded so a dropped claim is visible rather than absent.", ""]
        for item in record["rejected"]:
            lines.append(f"- {item.get('candidate')} / {item.get('source')}: "
                         f"{item.get('reason')}")
        lines.append("")
    lines += ["## Untrusted page content", ""]
    if record["injections"]:
        lines.append("Instruction-like text was found in page content and was treated as data. "
                     "It did not reach the agent as an instruction, and any claim it tried to "
                     "plant still had to quote the page.")
        lines.append("")
        for item in record["injections"]:
            for found in item["found"]:
                lines.append(f"- {item['candidate']} / {item['source']}: "
                             f"matched `{found['matched']}`")
    else:
        lines.append("No recognised injection patterns in the pages read. Detection is "
                     "observability only: the defences are the allowlist in the route handler, "
                     "the data-delimited prompt, strict JSON parsing and the quote check.")
    if record["blocked_requests"]:
        lines += ["", f"{len(record['blocked_requests'])} request(s) were blocked as off-allowlist "
                      "or absent from the cache."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m evidence.run",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--result", type=Path, required=True,
                        help="AntibioticCandidate result JSON, for the top candidates")
    parser.add_argument("--cache", type=Path, required=True, help="recorded-run directory")
    parser.add_argument("--mode", default=REPLAY, choices=["live", "record", "replay"])
    parser.add_argument("--transcript", type=Path,
                        help="recorded model replies (default: <cache>/transcript.json)")
    parser.add_argument("--top", type=int, default=TOP_N)
    parser.add_argument("--out", type=Path, help="write record.json and record.md here")
    args = parser.parse_args(argv)

    try:
        result = json.loads(args.result.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: {args.result}: {exc}", file=sys.stderr)
        return 2
    candidates = top_candidates(result, args.top)
    if not candidates:
        print("error: the result has no ranked candidates", file=sys.stderr)
        return 2

    transcript = args.transcript or (args.cache / "transcript.json")
    if args.mode == REPLAY:
        try:
            model = RecordedModel.from_file(transcript)
        except (ModelError, OSError, ValueError, KeyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        print("error: live and record modes need a model. Wire one in by passing a callable "
              "to evidence.run.run(); this CLI only replays a recorded run.", file=sys.stderr)
        return 2

    try:
        record = run(candidates, args.cache, model, mode=args.mode)
    except (SessionError, ModelError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(as_markdown(record))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                                              encoding="utf-8", newline="\n")
        (args.out / "record.md").write_text(as_markdown(record), encoding="utf-8", newline="\n")
    return 0 if not record["counts"]["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
