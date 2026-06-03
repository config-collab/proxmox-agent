"""
Scrapes Proxmox VE documentation into a flat JSON corpus.
Run once (or on demand) — takes ~30s on a Pi.

Output: ~/.proxmox-agent/docs_corpus.json
Each entry: {title, url, section, text, chunk_id}
"""
import json
import os
import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser

CORPUS_PATH = os.path.expanduser("~/.proxmox-agent/docs_corpus.json")

# Chapters to scrape — ordered by usefulness for a homelab operator
DOC_PAGES = [
    # Core VM + container management
    ("qm",       "https://pve.proxmox.com/pve-docs/chapter-qm.html"),
    ("pct",      "https://pve.proxmox.com/pve-docs/chapter-pct.html"),
    # Storage + backup
    ("pvesm",    "https://pve.proxmox.com/pve-docs/chapter-pvesm.html"),
    ("vzdump",   "https://pve.proxmox.com/pve-docs/chapter-vzdump.html"),
    # Network + security
    ("pvefw",    "https://pve.proxmox.com/pve-docs/chapter-pvefw.html"),     # was "firewall" → 404
    # Administration
    ("sysadmin", "https://pve.proxmox.com/pve-docs/chapter-sysadmin.html"),
    ("pvenode",  "https://pve.proxmox.com/pve-docs/chapter-pvenode.html"),   # node management
    # Cluster
    ("pvecm",    "https://pve.proxmox.com/pve-docs/chapter-pvecm.html"),
    ("ha",       "https://pve.proxmox.com/pve-docs/chapter-ha-manager.html"),# high availability
    # PBS — separate domain
    ("pbs",      "https://pbs.proxmox.com/docs/backup-client.html"),          # PBS backup client
]

CHUNK_WORDS   = 350   # target words per chunk
CHUNK_OVERLAP = 50    # words of overlap between adjacent chunks
MIN_WORDS     = 40    # discard chunks shorter than this
REQUEST_DELAY = 1.5   # seconds between requests — be a good citizen


# ── HTML → plain text ──────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Minimal HTML→text parser. Tracks h2/h3 headings for section titles."""

    def __init__(self):
        super().__init__()
        self.sections: list[dict] = []   # [{title, text}]
        self._current_title = ""
        self._current_buf: list[str] = []
        self._in_heading = False
        self._heading_buf: list[str] = []
        self._skip_tags = {"script", "style", "nav", "header", "footer"}
        self._skip_depth = 0
        self._tag_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        self._tag_stack.append(tag)
        if tag in self._skip_tags:
            self._skip_depth += 1
        if tag in ("h2", "h3") and self._skip_depth == 0:
            self._flush_section()
            self._in_heading = True
            self._heading_buf = []

    def handle_endtag(self, tag):
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        if tag in self._skip_tags:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag in ("h2", "h3") and self._in_heading:
            self._in_heading = False
            self._current_title = " ".join(self._heading_buf).strip()
            self._heading_buf = []

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        text = data.strip()
        if not text:
            return
        if self._in_heading:
            self._heading_buf.append(text)
        else:
            self._current_buf.append(text)

    def _flush_section(self):
        text = " ".join(self._current_buf).strip()
        text = re.sub(r"\s+", " ", text)
        if text and self._current_title:
            self.sections.append({"title": self._current_title, "text": text})
        self._current_buf = []

    def close(self):
        self._flush_section()
        super().close()


def _fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "proxmox-agent-docs-indexer/1.0 (homelab; not a bot)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_sections(html: str) -> list[dict]:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.sections


def _chunk_section(section: dict, base_url: str, chapter: str, section_idx: int) -> list[dict]:
    """Split a long section into overlapping word-chunks."""
    words = section["text"].split()
    if len(words) < MIN_WORDS:
        return []

    chunks = []
    start = 0
    chunk_idx = 0
    while start < len(words):
        end = min(start + CHUNK_WORDS, len(words))
        chunk_text = " ".join(words[start:end])
        chunks.append({
            "chunk_id":  f"{chapter}-s{section_idx}-c{chunk_idx}",
            "title":     section["title"],
            "chapter":   chapter,
            "url":       base_url,
            "text":      chunk_text,
        })
        if end == len(words):
            break
        start = end - CHUNK_OVERLAP
        chunk_idx += 1

    return chunks


# ── Public API ─────────────────────────────────────────────────────────────────

def build_corpus(force: bool = False) -> list[dict]:
    """
    Scrape all doc pages and return the corpus.
    Saves to CORPUS_PATH. Skips scraping if corpus already exists (unless force=True).
    """
    if not force and os.path.exists(CORPUS_PATH):
        return load_corpus()

    print(f"[docs] Building corpus from {len(DOC_PAGES)} chapters ...")
    corpus: list[dict] = []

    for chapter, url in DOC_PAGES:
        try:
            print(f"  fetching {chapter} ...", end=" ", flush=True)
            html = _fetch(url)
            sections = _parse_sections(html)
            for i, sec in enumerate(sections):
                corpus.extend(_chunk_section(sec, url, chapter, i))
            print(f"{len(sections)} sections")
            time.sleep(REQUEST_DELAY)
        except Exception as exc:
            print(f"error: {exc}")

    os.makedirs(os.path.dirname(CORPUS_PATH), exist_ok=True)
    with open(CORPUS_PATH, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, separators=(",", ":"))

    print(f"[docs] Corpus saved: {len(corpus)} chunks → {CORPUS_PATH}")
    return corpus


def load_corpus() -> list[dict]:
    if not os.path.exists(CORPUS_PATH):
        return []
    with open(CORPUS_PATH, encoding="utf-8") as f:
        return json.load(f)


def corpus_exists() -> bool:
    return os.path.exists(CORPUS_PATH)


def corpus_stats() -> str:
    if not corpus_exists():
        return "not built — run build_corpus()"
    corpus = load_corpus()
    chapters = {}
    for c in corpus:
        chapters[c["chapter"]] = chapters.get(c["chapter"], 0) + 1
    size_kb = os.path.getsize(CORPUS_PATH) // 1024
    lines = [f"{len(corpus)} chunks, {size_kb} KB"]
    for ch, n in sorted(chapters.items()):
        lines.append(f"  {ch}: {n} chunks")
    return "\n".join(lines)


if __name__ == "__main__":
    build_corpus(force=True)
    print(corpus_stats())
