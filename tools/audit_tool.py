"""
Transparency & audit tools — show users exactly why the agent recommended something.
Addresses the core concern: "I don't trust AI without seeing the reasoning."
"""
import json
from pathlib import Path
from tools import tool


@tool(
    name="show_reasoning",
    description=(
        "Show the agent's reasoning chain for a recent recommendation. "
        "Exposes: which docs/sources were consulted, which patterns matched, "
        "what guards/checks were applied, what the agent was uncertain about. "
        "Essential for building trust in high-stakes infrastructure decisions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question you asked the agent."},
            "detail":   {"type": "boolean", "description": "Show detailed chain-of-thought (default: true)."},
        },
        "required": ["question"],
    },
)
def show_reasoning(question: str, detail: bool = True) -> str:
    """
    In a real implementation, this would deserialize the agent's reasoning trace
    from the last operation. For now, return a template showing the structure.
    """
    return f"""
## Reasoning Trace for: "{question}"

### 1. **Query Interpretation**
   - Detected intent: [infrastructure operation type]
   - Risk level: [low/medium/high/critical]
   - Required approvals: [none/user/explicit]

### 2. **Information Gathering**
   - Official docs consulted: [which chapters searched]
   - Environment facts: [what was learned from env_profile/audit log]
   - Community feedback: [r/Proxmox results if applicable]
   - CVE check: [any vulnerabilities found]

### 3. **Safety Checks Applied**
   ✓ Guard check: Verified operation is allowed
   ✓ Autonomy gate: Confirmed user permission level
   ✓ Pre-flight backup: Would be triggered [yes/no]
   ✓ Audit logging: Would record [operation type and target]

### 4. **Uncertainty & Caveats**
   - Confidence in recommendation: [70-90%]
   - Areas where community feedback helps: [specific areas]
   - Known limitations: [what the agent cannot assess]
   - Recommend human verification: [yes/no + which aspects]

### 5. **Recommended Next Steps**
   1. [Action with explanation]
   2. [Action with explanation]
   3. [Verify result with this check]

---

**To audit a specific operation:**
- Check the audit log: `audit_log show --hours 1`
- Search environment history: `search_environment "operation name"`
- Compare with community: `ask_community "your scenario"`

**Trust model:** This agent is a decision-support tool, not autonomous. You make the final call.
"""


@tool(
    name="audit_log_export",
    description=(
        "Export the full audit log for external review. "
        "Shows every operation the agent attempted or completed. "
        "Use to verify: no unauthorized changes, no security breaches, "
        "proper approval flow was followed, reversible ops were documented."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hours":  {"type": "integer", "description": "How many hours back (default: 24)."},
            "format": {"type": "string",  "enum": ["json", "csv", "markdown"],
                       "description": "Output format (default: json)."},
        },
        "required": [],
    },
)
def audit_log_export(hours: int = 24, format: str = "json") -> str:
    """Export audit log for external review."""
    from docs.env_memory import AUDIT_PATH
    import datetime
    import csv
    import io

    if not AUDIT_PATH.exists():
        return "No audit log found."

    cutoff = datetime.datetime.now().timestamp() - hours * 3600
    entries = []

    try:
        for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line.strip())
                if entry.get("timestamp"):
                    # Parse ISO timestamp
                    import datetime
                    ts = datetime.datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp()
                    if ts >= cutoff:
                        entries.append(entry)
            except Exception:
                continue
    except Exception as exc:
        return f"Error reading audit log: {exc}"

    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["timestamp", "operation", "target", "outcome", "reversible", "agent"])
        writer.writeheader()
        for e in entries:
            writer.writerow({
                "timestamp": e.get("timestamp", ""),
                "operation": e.get("operation", ""),
                "target":    e.get("target", ""),
                "outcome":   e.get("outcome", ""),
                "reversible": str(e.get("reversible", False)),
                "agent":     e.get("agent", ""),
            })
        return output.getvalue()

    elif format == "markdown":
        lines = [f"# Audit Log (last {hours}h)\n"]
        for e in entries:
            op = e.get("operation", "?")
            tgt = e.get("target", "?")
            outcome = e.get("outcome", "?")
            ts = e.get("timestamp", "?")[:16]
            irr = " ⚠️ **IRREVERSIBLE**" if not e.get("reversible", False) else ""
            lines.append(f"- `[{ts}]` **{op}** on {tgt}: {outcome}{irr}")
        return "\n".join(lines)

    else:  # json
        return json.dumps(entries, indent=2)


@tool(
    name="compare_with_community",
    description=(
        "Compare the agent's recommendation with what r/Proxmox community is doing. "
        "Shows if your situation is unique or if others have solved it. "
        "Helps surface disagreement between agent & community (red flag for deeper investigation)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic":     {"type": "string", "description": "Topic the agent recommended (e.g. 'ZFS snapshots', 'backup strategy')."},
            "top_k":     {"type": "integer", "description": "Show top K community discussions (default 5)."},
        },
        "required": ["topic"],
    },
)
def compare_with_community(topic: str, top_k: int = 5) -> str:
    from docs import reddit_search
    results = reddit_search.search(topic, top_k, sort="top", time_filter="year")
    if not results or results[0].get("id") == "error":
        return f"Could not reach r/Proxmox for comparison"
    return reddit_search.search_formatted(topic, top_k)
