"""A trial: retrieval-augmented answers from PubMed and ClinicalTrials.gov, built on LangChain.

    search pages (headless Chromium)  ->  one Document per result card  ->  vector index
        ->  retrieve the cards that bear on one question  ->  model  ->  quote check

What is LangChain and what is not. LangChain supplies the pieces a RAG is made of: ``Document``,
a ``BaseLoader`` that reads the web through Playwright, an ``Embeddings`` interface, an
in-memory vector store, a retriever and a runnable chain. The browser is the existing
``evidence.session.Session`` and is not replaced, so the host allowlist, record/replay and the
step log still apply. The answer still goes through ``evidence.extract.accept``: a claim is kept
only if its quote is on a retrieved card, and the claim carries that card's URL. Retrieval only
chooses *which* text the model sees. It does not make the model's reply any more trustworthy,
and nothing here treats the reply as true without the quote.

Two limits found by running it against the live sites (November 2026):

* PubMed returns 403 to headless Chromium for article pages, so this reads the search-results
  page only. A card is the title, citation, PMID and the start of the abstract, not the full
  abstract. It is not worked around. A question the snippet cannot answer comes back as
  ``no record found``.
* ClinicalTrials.gov draws its cards with JavaScript, so the loader waits for them.

The default embedding is lexical (hashed bag of words). It is deterministic and needs no key or
download, which keeps the trial reproducible, but it ranks by shared words, not meaning. Pass any
LangChain ``Embeddings`` to ``Corpus.build`` to use a semantic one.

This is a trial. It is not wired into the app or the ranking.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from urllib.parse import quote_plus

from .extract import (ExtractionError, accept, build_prompt, fill_unanswered,
                      find_injections, new_nonce, normalise, parse_reply)
from .run import ModelError, Reply
from .session import Session, StepLog

try:  # LangChain is optional for the rest of the package; this module needs langchain-core.
    from langchain_core.document_loaders import BaseLoader
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings
    from langchain_core.runnables import RunnableLambda
    from langchain_core.vectorstores import InMemoryVectorStore
except ImportError as exc:  # pragma: no cover
    raise ImportError("evidence.rag needs langchain-core: pip install langchain-core") from exc

# What a reader wants to know when deciding whether to spend effort on a candidate. Each has
# a retrieval query (the words used to find the cards that might answer it).
QUESTIONS = ("resistance_link", "clinical_outcome", "activity_in_pathogen")
QUESTION_QUERIES = {
    "resistance_link": "cross-resistance reduced susceptibility efflux inactivation mutation "
                       "resistant strains",
    "clinical_outcome": "trial terminated withdrawn failed futility adverse events toxicity "
                        "discontinued safety",
    "activity_in_pathogen": "in vitro activity MIC inhibits susceptible isolates bactericidal "
                            "efficacy",
}

PUBMED = "https://pubmed.ncbi.nlm.nih.gov/?term={term}"
CLINICALTRIALS = "https://clinicaltrials.gov/search?term={term}"

# Per source: how to find the result cards, their link, and when a JS page has drawn them.
SOURCES = {
    "pubmed": {
        "url": PUBMED,
        "card": "article.full-docsum",
        "link": "a.docsum-title",
        "ready_js": None,
        "id": re.compile(r"PMID:\s*(\d+)"),
    },
    "clinicaltrials": {
        "url": CLINICALTRIALS,
        "card": "ctg-search-hit-card",
        "link": "a[href*='/study/NCT']",
        "ready_js": "document.querySelector('ctg-search-hit-card') !== null || "
                    "/No Studies found/i.test(document.body.innerText)",
        "id": re.compile(r"(NCT\d{8})"),
    },
}


# ------------------------------------------------------------------ embeddings and chunking

_STOP = frozenset("a an and are as at be but by for from has have in into is it its of on or "
                  "that the their there these this to was were which with".split())
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]+")


def tokens(text: str) -> list:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP]


class LexicalEmbeddings(Embeddings):
    """Hashed bag-of-words vectors, L2-normalised. Deterministic; ranks by shared words only."""

    def __init__(self, dims: int = 2048):
        self.dims = dims

    def _vector(self, text: str) -> list:
        counts = Counter()
        for token in tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            counts[int.from_bytes(digest, "big") % self.dims] += 1
        vector = [0.0] * self.dims
        for index, n in counts.items():
            vector[index] = 1.0 + math.log(n)
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list) -> list:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list:
        return self._vector(text)


def split_documents(documents: list, size: int = 900, overlap: int = 120) -> list:
    """Cut long documents at sentence ends into overlapping chunks. A card is usually one chunk."""
    out = []
    for doc in documents:
        text = doc.page_content
        if len(text) <= size:
            out.append(doc)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunk = ""
        for sentence in sentences:
            if chunk and len(chunk) + len(sentence) + 1 > size:
                out.append(Document(page_content=chunk, metadata=dict(doc.metadata)))
                chunk = chunk[-overlap:].split(" ", 1)[-1] if overlap else ""
            chunk = f"{chunk} {sentence}".strip()
        if chunk:
            out.append(Document(page_content=chunk, metadata=dict(doc.metadata)))
    return out


# ------------------------------------------------------------------ loading

class BrowserLoader(BaseLoader):
    """Search both sources in the session's browser, one ``Document`` per result card.

    Each query is run on each source. Documents are de-duplicated by record id (PMID or NCT
    number) so a card found by two queries counts once. A search with no results yields nothing,
    and the caller's ``no record found`` follows from that.
    """

    def __init__(self, session: Session, queries: list, *, per_source: int = 10):
        self.session = session
        self.queries = queries
        self.per_source = per_source
        self.searches: list = []  # (source, query, url, cards found), for the run record

    def lazy_load(self):
        seen = set()
        for query in self.queries:
            for source, spec in SOURCES.items():
                url = spec["url"].format(term=quote_plus(query))
                self.session.open(url, note=f"{query!r} on {source}", ready_js=spec["ready_js"])
                cards = self.session.cards(spec["card"], link=spec["link"])[: self.per_source]
                self.searches.append({"source": source, "query": query, "url": url,
                                      "cards": len(cards)})
                for card in cards:
                    text = normalise(card["text"])
                    match = spec["id"].search(card["text"])
                    record_id = match.group(1) if match else None
                    key = (source, record_id or text[:80])
                    if not text or key in seen:
                        continue
                    seen.add(key)
                    yield Document(page_content=text, metadata={
                        "source": source, "id": record_id, "query": query,
                        "url": card["href"] or url, "search_url": url,
                    })


# ------------------------------------------------------------------ index and answer

@dataclass
class Corpus:
    """The retrieved cards, indexed. ``retrieve`` is the R in RAG."""

    documents: list
    store: InMemoryVectorStore
    searches: list

    @classmethod
    def build(cls, session: Session, queries: list, *, embeddings: Embeddings | None = None,
              per_source: int = 10) -> "Corpus":
        loader = BrowserLoader(session, queries, per_source=per_source)
        documents = split_documents(list(loader.lazy_load()))
        store = InMemoryVectorStore(embeddings or LexicalEmbeddings())
        if documents:
            store.add_documents(documents)
        return cls(documents, store, loader.searches)

    def retrieve(self, query: str, k: int = 6) -> list:
        if not self.documents:
            return []
        return self.store.as_retriever(search_kwargs={"k": k}).invoke(query)


def context_block(chunks: list) -> str:
    """The retrieved cards as numbered, URL-labelled passages, for the prompt."""
    return "\n\n".join(f"[{i}] ({c.metadata['source']}) {c.metadata['url']}\n{c.page_content}"
                       for i, c in enumerate(chunks, 1))


def answer_question(corpus: Corpus, model, candidate: str, question: str, *, k: int = 6,
                    log: StepLog | None = None) -> dict:
    """Retrieve for one question, ask the model, keep only the claims a retrieved card supports."""
    started = time.monotonic()
    chunks = corpus.retrieve(f"{candidate} {QUESTION_QUERIES[question]}", k)
    if log:
        log.add("retrieve", seconds=round(time.monotonic() - started, 3),
                note=f"{question}: {len(chunks)} of {len(corpus.documents)} passages")
    fallback = corpus.searches[0]["url"] if corpus.searches else ""
    result = {"question": question, "claims": [], "rejected": [], "injections": [],
              "retrieved": [{"url": c.metadata["url"], "source": c.metadata["source"],
                             "id": c.metadata["id"]} for c in chunks]}
    if not chunks:
        result["claims"] = fill_unanswered([], candidate=candidate, url=fallback,
                                           source="pubmed", questions=(question,))
        return result

    for chunk in chunks:
        seen = find_injections(chunk.page_content)
        if seen:
            result["injections"].append({"url": chunk.metadata["url"], "found": seen})

    prompt = build_prompt(candidate, context_block(chunks), fallback, "pubmed+clinicaltrials",
                          new_nonce(), questions=(question,))
    started = time.monotonic()
    try:
        reply = model(prompt, key=f"{candidate}|{question}")
    except ModelError as exc:
        if log:
            log.add("model_failed", note=str(exc)[:80])
        result["error"] = str(exc)
        return result
    if log:
        log.add("model", model=reply.model, prompt_tokens=reply.prompt_tokens,
                completion_tokens=reply.completion_tokens,
                seconds=round(time.monotonic() - started, 3), note=f"{candidate} / {question}")

    try:
        proposed = parse_reply(reply.text, (question,))
    except ExtractionError as exc:
        result["rejected"].append({"reason": f"unusable reply: {exc}"})
        proposed = []

    accepted = []
    for item in proposed:
        # The quote must be on one retrieved card. That card, not the search page, is the source.
        for chunk in chunks:
            took, dropped = accept([item], candidate=candidate, page_text=chunk.page_content,
                                   url=chunk.metadata["url"], source=chunk.metadata["source"])
            if took:
                accepted.extend(took)
                break
        else:
            reason = dropped[0]["reason"] if dropped else "not supported by any retrieved card"
            result["rejected"].append({**item, "reason": reason})
    result["claims"] = fill_unanswered(accepted, candidate=candidate, url=fallback,
                                       source="pubmed", questions=(question,))
    return result


def screen_candidate(corpus: Corpus, model, candidate: str, *, k: int = 6,
                     log: StepLog | None = None) -> dict:
    """Ask every question about one candidate. As a LangChain chain it is ``screen_chain``."""
    claims, rejected, injections, retrieved, errors = [], [], [], {}, []
    for question in QUESTIONS:
        found = answer_question(corpus, model, candidate, question, k=k, log=log)
        claims.extend(found["claims"])
        rejected.extend(found["rejected"])
        injections.extend(found["injections"])
        retrieved[question] = found["retrieved"]
        if "error" in found:
            errors.append({"question": question, "error": found["error"]})
    cited = [c for c in claims if not c.is_no_record]
    return {"candidate": candidate, "claims": [c.as_dict() for c in claims],
            "with_citation": len(cited), "rejected": rejected, "injections": injections,
            "retrieved": retrieved, "errors": errors,
            "documents": len(corpus.documents), "searches": corpus.searches}


def screen_chain(corpus: Corpus, model, *, k: int = 6, log: StepLog | None = None):
    """The same pipeline as a LangChain runnable: ``{"candidate": ...}`` in, a record out."""
    return RunnableLambda(
        lambda inputs: screen_candidate(corpus, model, inputs["candidate"], k=k, log=log))


# ------------------------------------------------------------------ models

def langchain_model(chat_model, name: str | None = None):
    """Adapt any LangChain chat model (``ChatAnthropic``, ``ChatOpenAI``, ...) to ``model(prompt, key=)``.

    Not exercised against a live provider in this repo's tests: those use LangChain's fake chat
    models. The reply still has to pass the quote check, whatever model produced it.
    """
    label = name or getattr(chat_model, "model", None) or type(chat_model).__name__

    def call(prompt: str, *, key: str) -> Reply:
        try:
            message = chat_model.invoke(prompt)
        except Exception as exc:
            raise ModelError(f"{label}: {type(exc).__name__}") from exc
        content = message.content
        if isinstance(content, list):
            content = "".join(p.get("text", "") if isinstance(p, dict) else str(p)
                              for p in content)
        usage = getattr(message, "usage_metadata", None) or {}
        return Reply(str(content), str(label), int(usage.get("input_tokens", 0)),
                     int(usage.get("output_tokens", 0)))

    return call


# Words that make a sentence relevant to a question, for the no-LLM baseline.
_BASELINE = {
    "resistance_link": re.compile(r"cross-resistan|resistan\w+|reduced susceptib|efflux|mutation",
                                  re.I),
    "clinical_outcome": re.compile(r"terminated|withdrawn|futility|discontinu\w+|adverse|"
                                   r"toxicit\w+|safety|completed", re.I),
    "activity_in_pathogen": re.compile(r"in vitro|MIC\b|activity against|susceptib\w+|"
                                       r"bactericidal|inhibit\w+", re.I),
}


def baseline_model(prompt: str, *, key: str) -> Reply:
    """A no-LLM control: quotes the first sentence on a retrieved card that matches the question.

    It cannot read negation ("no cross-resistance" matches "resistance"), so its answers are
    worded as what the card mentions, never as a finding. It exists to say how much of a result
    is retrieval and how much is the model.
    """
    question = key.rsplit("|", 1)[-1]
    pattern = _BASELINE[question]
    body = prompt.split("-----", 2)[-1]
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
        sentence = normalise(sentence)
        if len(sentence) >= 40 and pattern.search(sentence) and not sentence.startswith(
                ("[", "END PAGE")):
            return Reply(json.dumps({"claims": [{
                "question": question,
                "answer": f"a retrieved record mentions: {sentence[:160]}",
                "quote": sentence}]}), "keyword-baseline")
    return Reply(json.dumps({"claims": []}), "keyword-baseline")


# ------------------------------------------------------------------ command line

def queries_for(candidate: str, context: str) -> list:
    """Broad (the name alone) and narrow (the name with the resistance context)."""
    return [candidate] + ([f"{candidate} {context}"] if context.strip() else [])


def main(argv=None) -> int:
    import argparse
    import sys
    from pathlib import Path

    from .session import LIVE, RECORD, REPLAY

    parser = argparse.ArgumentParser(prog="python -m evidence.rag", description=__doc__.split("\n")[0])
    parser.add_argument("candidates", nargs="+", help="drug names")
    parser.add_argument("--context", default="", help="resistance context, e.g. 'oxazolidinone cfr'")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--mode", default=REPLAY, choices=[LIVE, RECORD, REPLAY])
    parser.add_argument("--per-source", type=int, default=10)
    parser.add_argument("-k", type=int, default=6, help="passages retrieved per question")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    records = []
    log = StepLog()
    try:
        with Session(args.cache, mode=args.mode, log=log) as session:
            for candidate in args.candidates:
                corpus = Corpus.build(session, queries_for(candidate, args.context),
                                      per_source=args.per_source)
                records.append(screen_candidate(corpus, baseline_model, candidate, k=args.k,
                                                log=log))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = {"mode": args.mode, "model": "keyword-baseline", "records": records,
           "step_table": log.render()}
    text = json.dumps(out, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    for rec in records:
        print(f"{rec['candidate']}: {rec['documents']} passages, "
              f"{rec['with_citation']}/{len(rec['claims'])} claims cited, "
              f"{len(rec['rejected'])} dropped")
        for claim in rec["claims"]:
            if claim["answer"].lower() != "no record found":
                print(f"  {claim['question']}: {claim['answer'][:110]}\n    <{claim['url']}>")
    print(log.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
