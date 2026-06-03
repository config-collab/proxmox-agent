"""
Environment knowledge base — makes the agent aware of its own context.

Builds searchable corpus chunks from:
  1. env_profile.json   — guests, their purpose, IPs, known issues
  2. audit.jsonl        — past operations: successes, failures, patterns
  3. .env               — connection topology, storage targets

These chunks are merged into the BM25 index so queries like
"what is pihole?", "did patching pihole ever fail?", or
"which guest runs Home Assistant?" get instant answers from
local knowledge rather than the LLM guessing.

Rebuild whenever env_profile changes (called by run_discovery).
"""
import json
import os
import re
from pathlib import Path

PROFILE_PATH  = Path.home() / ".proxmox-agent" / "env_profile.json"
AUDIT_PATH    = Path(os.path.expanduser(os.environ.get("AUDIT_LOG_PATH",
                    "~/.proxmox-agent/audit.jsonl")))
ENV_CORPUS    = Path.home() / ".proxmox-agent" / "env_corpus.json"


def _ts_to_date(ts: str) -> str:
    return ts[:10] if ts else "unknown"


def build(force: bool = False) -> list[dict]:
    """Build and save the environment corpus. Returns the chunk list."""
    if ENV_CORPUS.exists() and not force:
        try:
            return json.loads(ENV_CORPUS.read_text(encoding="utf-8"))
        except Exception:
            pass

    chunks: list[dict] = []

    # ── 1. env_profile: guest inventory ───────────────────────────────────────
    if PROFILE_PATH.exists():
        try:
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            node = profile.get("node_name", "pve")
            date = _ts_to_date(profile.get("profile_date", ""))

            # Summary chunk
            summary = profile.get("summary", "")
            if summary:
                chunks.append({
                    "chunk_id": "env-summary",
                    "title":    f"Environment summary ({node})",
                    "chapter":  "environment",
                    "url":      "",
                    "text":     summary,
                })

            # Per-guest chunks
            for g in profile.get("guests", []):
                name    = g.get("name", "?")
                purpose = g.get("purpose", "unknown purpose")
                ip      = g.get("ip", "")
                status  = g.get("status", "unknown")
                gtype   = g.get("type", "vm")
                vmid    = g.get("vmid", "?")
                text = (
                    f"{name} is a {gtype} (VMID {vmid}) running on {node}. "
                    f"Purpose: {purpose}. Status: {status}. "
                    + (f"IP address: {ip}. " if ip else "")
                    + f"Scanned on {date}."
                )
                chunks.append({
                    "chunk_id": f"env-guest-{name}",
                    "title":    f"Guest: {name}",
                    "chapter":  "environment",
                    "url":      "",
                    "text":     text,
                })

            # Action items as searchable chunks
            for i, item in enumerate(profile.get("action_items", [])):
                priority = item.get("priority", "medium")
                desc     = item.get("description", "")
                if desc:
                    chunks.append({
                        "chunk_id": f"env-action-{i}",
                        "title":    f"Recommended action [{priority.upper()}]",
                        "chapter":  "environment",
                        "url":      "",
                        "text":     desc,
                    })
        except Exception as e:
            chunks.append({
                "chunk_id": "env-profile-error",
                "title":    "Environment profile (load error)",
                "chapter":  "environment",
                "url":      "",
                "text":     f"Could not load env_profile: {e}",
            })

    # ── 2. audit log: operation history ───────────────────────────────────────
    if AUDIT_PATH.exists():
        errors: list[dict]    = []
        successes: list[dict] = []
        try:
            lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()
            for line in lines[-500:]:   # last 500 operations
                try:
                    entry = json.loads(line.strip())
                except Exception:
                    continue
                op      = entry.get("operation", "")
                target  = entry.get("target", "")
                outcome = entry.get("outcome", "")
                ts      = _ts_to_date(entry.get("timestamp", ""))
                if outcome == "error" or "error" in outcome.lower():
                    errors.append({"op": op, "target": target, "outcome": outcome, "date": ts})
                elif outcome in ("ok", "dry-run"):
                    successes.append({"op": op, "target": target, "date": ts})
        except Exception:
            pass

        if errors:
            error_text = "Past operation failures:\n" + "\n".join(
                f"- [{e['date']}] {e['op']} on {e['target']}: {e['outcome']}"
                for e in errors[-20:]
            )
            chunks.append({
                "chunk_id": "env-audit-errors",
                "title":    "Past operation failures",
                "chapter":  "environment",
                "url":      "",
                "text":     error_text,
            })

        if successes:
            # Group by operation type
            by_op: dict[str, list[str]] = {}
            for s in successes:
                by_op.setdefault(s["op"], []).append(s["target"])
            lines = []
            for op, targets in list(by_op.items())[:10]:
                unique = list(dict.fromkeys(targets))[:5]
                lines.append(f"- {op}: applied to {', '.join(unique)}")
            chunks.append({
                "chunk_id": "env-audit-successes",
                "title":    "Past successful operations",
                "chapter":  "environment",
                "url":      "",
                "text":     "Successful operations history:\n" + "\n".join(lines),
            })

    # ── 3. .env topology ──────────────────────────────────────────────────────
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        topo_lines = ["Infrastructure topology from configuration:"]
        guest_ips: dict[str, str] = {}
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k == "PROXMOX_HOST":
                    topo_lines.append(f"Proxmox host IP: {v}")
                elif k == "PBS_HOST":
                    topo_lines.append(f"PBS (backup server) IP: {v}")
                elif k.startswith("GUEST_IP_"):
                    name = k[len("GUEST_IP_"):]
                    guest_ips[name] = v
                    topo_lines.append(f"Guest {name} IP: {v}")
        except Exception:
            pass
        if len(topo_lines) > 1:
            chunks.append({
                "chunk_id": "env-topology",
                "title":    "Network topology",
                "chapter":  "environment",
                "url":      "",
                "text":     "\n".join(topo_lines),
            })

    # Save
    ENV_CORPUS.parent.mkdir(parents=True, exist_ok=True)
    ENV_CORPUS.write_text(json.dumps(chunks, indent=2), encoding="utf-8")
    return chunks


def load() -> list[dict]:
    """Load cached env corpus, building it if needed."""
    if ENV_CORPUS.exists():
        try:
            return json.loads(ENV_CORPUS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return build(force=True)
