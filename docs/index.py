"""
BM25 search index over the Proxmox docs corpus.
Index is built once per process and kept in memory (~5 MB RAM).
Zero external dependencies — BM25Okapi is vendored below.
"""
from __future__ import annotations
import re
import math
import urllib.request
import urllib.parse
from collections import Counter as _Counter

from docs.scraper import load_corpus, build_corpus, corpus_exists
from docs import env_memory as _env_mem


# ── Vendored BM25Okapi (replaces rank_bm25 package, no numpy needed) ──────────

class BM25Okapi:
    """Okapi BM25 — k1=1.5, b=0.75. Pure Python, no dependencies."""
    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.N = len(corpus)
        self.avgdl = sum(len(d) for d in corpus) / max(1, self.N)
        self.doc_freqs: list[_Counter] = []
        self.doc_len:   list[int]      = []
        df: dict[str, int] = {}
        for doc in corpus:
            f = _Counter(doc)
            self.doc_freqs.append(f)
            self.doc_len.append(len(doc))
            for w in f:
                df[w] = df.get(w, 0) + 1
        self.idf = {
            w: math.log((self.N - n + 0.5) / (n + 0.5) + 1)
            for w, n in df.items()
        }

    def get_scores(self, query: list[str]) -> list[float]:
        scores = [0.0] * self.N
        for q in set(query):
            idf = self.idf.get(q, 0.0)
            if not idf:
                continue
            for i, (f, dl) in enumerate(zip(self.doc_freqs, self.doc_len)):
                tf = f.get(q, 0)
                if not tf:
                    continue
                scores[i] += idf * tf * (self.k1 + 1) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                )
        return scores


# Lazy-loaded globals — built on first search call
_index: BM25Okapi | None = None
_corpus: list[dict] = []

FORUM_SEARCH_URL = "https://forum.proxmox.com/search.json?q={query}&order=latest"
FORUM_RESULT_LIMIT = 5


# ── Tokeniser ──────────────────────────────────────────────────────────────────

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of",
    "and", "or", "in", "on", "at", "for", "with", "this", "that", "it", "as",
    "by", "from", "can", "will", "you", "your", "we", "i",
}


def _tokenise(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_\-]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


# ── Index ──────────────────────────────────────────────────────────────────────

def _ensure_index():
    global _index, _corpus
    if _index is not None:
        return

    if not corpus_exists():
        print("[docs] Corpus not found — building now (one-time, ~30s) ...")
        build_corpus()

    docs_chunks = load_corpus()
    if not docs_chunks:
        raise RuntimeError("Corpus is empty — run docs/scraper.py to rebuild")

    # Merge environment knowledge (guests, audit history, topology)
    env_chunks = _env_mem.load()

    _corpus = docs_chunks + env_chunks
    tokenised = [_tokenise(f"{c['title']} {c['text']}") for c in _corpus]
    _index = BM25Okapi(tokenised)


def _keyword_boost(scores: list[float], tokens: list[str]) -> list[float]:
    """
    Boost chunks whose raw text contains query tokens as exact substrings.
    This lifts environment chunks (guest names, IPs) that BM25 undersells
    because their corpus is tiny relative to the doc pages.
    """
    boosted = list(scores)
    for i, chunk in enumerate(_corpus):
        text_lower = (chunk.get("title", "") + " " + chunk.get("text", "")).lower()
        for t in tokens:
            if t in text_lower:
                # Extra boost for environment chunks — they're authoritative for env facts
                w = 1.5 if chunk.get("chapter") == "environment" else 0.5
                boosted[i] += w
    return boosted


# ── Public API ─────────────────────────────────────────────────────────────────

def search(query: str, top_k: int = 4, source: str = "") -> list[dict]:
    """
    Hybrid BM25 + keyword-boost search across docs + environment knowledge.

    source: "" = all, "environment" = env facts only, "docs" = manual pages only
    """
    _ensure_index()
    tokens = _tokenise(query)
    if not tokens:
        return []

    scores = _index.get_scores(tokens)
    scores = _keyword_boost(scores, tokens)
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

    results = []
    seen_titles: set[str] = set()
    for idx, score in ranked:
        if len(results) >= top_k:
            break
        if score < 0.05:
            break
        chunk = _corpus[idx]
        if source and chunk.get("chapter") != source and not (source == "docs" and chunk.get("chapter") != "environment"):
            continue
        if chunk["title"] in seen_titles:
            continue
        seen_titles.add(chunk["title"])
        results.append({**chunk, "score": round(float(score), 3)})

    return results


def search_formatted(query: str, top_k: int = 4) -> str:
    """Return search results as a compact string for LLM injection."""
    results = search(query, top_k)
    if not results:
        return f"No docs found for: {query}"

    parts = []
    for r in results:
        src_label = "ENVIRONMENT" if r["chapter"] == "environment" else r["chapter"].upper()
        url_line  = f"\nSource: {r['url']}" if r.get("url") else ""
        parts.append(
            f"[{src_label} — {r['title']}]\n"
            f"{r['text'][:600]}"
            f"{url_line}"
        )
    return "\n\n---\n\n".join(parts)


def rebuild_env_index():
    """Force rebuild of environment knowledge and reset the search index."""
    global _index, _corpus
    _env_mem.build(force=True)
    _index  = None
    _corpus = []


def forum_search(query: str) -> str:
    """
    Live search the Proxmox forum via Discourse JSON API.
    Returns a compact summary of the top results.
    """
    try:
        encoded = urllib.parse.quote(query)
        url = FORUM_SEARCH_URL.format(query=encoded)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "proxmox-agent/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json
            data = json.loads(resp.read())
    except Exception as exc:
        return f"Forum search failed: {exc}"

    topics = data.get("topics", [])[:FORUM_RESULT_LIMIT]
    if not topics:
        return "No forum results found."

    lines = [f"Forum results for '{query}':"]
    for t in topics:
        title  = t.get("title", "?")
        slug   = t.get("slug", "")
        tid    = t.get("id", "")
        posts  = t.get("posts_count", "?")
        views  = t.get("views", "?")
        url    = f"https://forum.proxmox.com/t/{slug}/{tid}"
        lines.append(f"• {title} ({posts} posts, {views} views)\n  {url}")

    return "\n".join(lines)
