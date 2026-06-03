"""
Community Proxmox helper scripts search.
Source: https://github.com/community-scripts/ProxmoxVE

Scripts are one-liner bash installs run directly on the Proxmox host.
Results cached at ~/.proxmox-agent/helper_scripts.json (refreshed every 24h).
"""
import json
import os
import time
import urllib.request
from pathlib import Path

CACHE_PATH  = Path.home() / ".proxmox-agent" / "helper_scripts.json"
CACHE_TTL   = 24 * 3600   # seconds
RAW_BASE    = "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main"
GITHUB_API  = "https://api.github.com/repos/community-scripts/ProxmoxVE/contents"
WEBSITE     = "https://community-scripts.org/"

# Directories to scan
_DIRS = [
    ("ct",   "LXC Container"),
    ("vm",   "VM"),
    ("tools","Host Tool"),
    ("misc", "Misc"),
]


def _fetch_and_cache() -> list[dict]:
    scripts: list[dict] = []
    for d, category in _DIRS:
        try:
            req = urllib.request.Request(
                f"{GITHUB_API}/{d}",
                headers={"User-Agent": "proxmox-agent/1.0",
                         "Accept": "application/vnd.github.v3+json"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                files = json.loads(resp.read())
            for f in files:
                if not f["name"].endswith(".sh"):
                    continue
                stem = f["name"][:-3]
                scripts.append({
                    "name":     stem,
                    "label":    _to_label(stem),
                    "category": category,
                    "dir":      d,
                    "url":      f"{RAW_BASE}/{d}/{f['name']}",
                    "run_cmd":  f'bash -c "$(curl -fsSL {RAW_BASE}/{d}/{f["name"]})"',
                })
        except Exception:
            pass
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(scripts, indent=2), encoding="utf-8")
    return scripts


def _load() -> list[dict]:
    if CACHE_PATH.exists():
        try:
            age = time.time() - CACHE_PATH.stat().st_mtime
            if age < CACHE_TTL:
                return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _fetch_and_cache()


def _to_label(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").title()


def search(query: str, top_k: int = 8) -> list[dict]:
    scripts = _load()
    terms   = query.lower().split()
    scored  = []
    for s in scripts:
        haystack = f"{s['name']} {s['label']} {s['category']}".lower()
        score = sum(2 if t in s["name"].lower() else 1 for t in terms if t in haystack)
        if score:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:top_k]]


def refresh_cache() -> int:
    """Force refresh and return number of scripts fetched."""
    scripts = _fetch_and_cache()
    return len(scripts)


def search_formatted(query: str, top_k: int = 6) -> str:
    results = search(query, top_k)
    if not results:
        return f"No community scripts matching '{query}'. Try: homeassistant, nginx, vaultwarden, pihole, nextcloud."
    lines = [f"Community Proxmox scripts matching '{query}' ({WEBSITE}):"]
    for r in results:
        lines.append(f"\n[{r['category']}] {r['label']}")
        lines.append(f"  Run on Proxmox host: {r['run_cmd']}")
    return "\n".join(lines)
