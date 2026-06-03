"""
Onboarding — first-run environment discovery.

On first run the agent:
  1. Connects and runs all diagnostic tools
  2. Feeds raw results to the LLM for synthesis
  3. LLM produces a structured environment profile + prioritised action list
  4. Profile saved to ~/.proxmox-agent/env_profile.json
  5. Returns the briefing text for the user

On subsequent runs: loads the saved profile and appends it to the system prompt
so the LLM starts with full environmental context.
"""
import json
import os
import datetime
import config
import llm
import tools   # registers all @tool decorators

PROFILE_PATH = os.path.expanduser("~/.proxmox-agent/env_profile.json")


def is_first_run() -> bool:
    return not os.path.exists(PROFILE_PATH)


def load_profile() -> dict | None:
    if not os.path.exists(PROFILE_PATH):
        return None
    try:
        with open(PROFILE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def save_profile(profile: dict):
    os.makedirs(os.path.dirname(PROFILE_PATH), exist_ok=True)
    with open(PROFILE_PATH, "w") as f:
        json.dump(profile, f, indent=2)


DISCOVERY_SYNTHESIS_PROMPT = """
You have just collected a full diagnostic snapshot of a Proxmox homelab environment.
The raw data from each tool is below.

Your job: synthesise this into a structured environment profile and a prioritised action list.

Output exactly this JSON structure (no markdown, no extra text — raw JSON only):
{
  "profile_date": "<ISO date>",
  "node_name": "<pve node name>",
  "pve_version": "<version string>",
  "guest_count": <int>,
  "guests": [
    {"id": <int>, "name": "<name>", "type": "vm|lxc", "status": "running|stopped", "purpose": "<inferred>"}
  ],
  "backup_health": "good|degraded|critical",
  "security_posture": "good|fair|poor",
  "patch_status": "current|behind|critical",
  "storage_health": "good|warning|critical",
  "pbs_connected": true|false,
  "action_items": [
    {"priority": 1, "severity": "CRITICAL|HIGH|MEDIUM", "title": "<short title>", "detail": "<what to do>", "tool": "<tool_name or null>"}
  ],
  "summary": "<2-3 sentence plain English summary of the environment and its current health>"
}

Action items should be ranked by severity and impact. Include at most 10.
The "tool" field should be the agent tool name the user can invoke to address it (e.g. "apply_patches", "check_pbs", "security_audit"), or null if it requires manual action.

Raw diagnostic data follows:
"""


def run_discovery(node: str = "pve") -> tuple[str, dict]:
    """
    Run all tools, synthesise with LLM, return (briefing_text, profile_dict).
    """
    print("\n[onboarding] Starting environment discovery — this takes ~60 seconds ...\n")
    raw_sections: dict[str, str] = {}

    steps = [
        ("get_inventory",  {"node": node},   "Inventory"),
        ("check_patches",  {},               "Patch status"),
        ("check_backups",  {"node": node},   "Backup status"),
        ("check_pbs",      {},               "PBS deep check"),
        ("security_audit", {"host_only": False}, "Security audit"),
    ]

    for tool_name, inputs, label in steps:
        print(f"  [{label}] ...", end=" ", flush=True)
        try:
            result = tools.dispatch(tool_name, inputs)
            raw_sections[label] = result
            print("done")
        except Exception as exc:
            raw_sections[label] = f"error: {exc}"
            print(f"error: {exc}")

    # Build synthesis prompt
    combined = DISCOVERY_SYNTHESIS_PROMPT
    for label, content in raw_sections.items():
        combined += f"\n\n=== {label} ===\n{content}"

    print("\n[onboarding] Synthesising with LLM ...")
    messages = [{"role": "user", "content": combined}]

    try:
        text, _ = llm.chat(messages)
        raw_json = text.strip() if text else "{}"
        # Strip markdown code fences if LLM wrapped the JSON
        if raw_json.startswith("```"):
            raw_json = raw_json.split("```")[1]
            if raw_json.startswith("json"):
                raw_json = raw_json[4:]
        profile = json.loads(raw_json)
    except Exception as exc:
        print(f"  [warn] LLM synthesis failed ({exc}) — saving raw data only")
        profile = {
            "profile_date": datetime.datetime.utcnow().isoformat() + "Z",
            "summary": "Profile synthesis failed — run individual tools manually.",
            "action_items": [],
            "raw_sections": raw_sections,
        }

    profile["profile_date"] = datetime.datetime.utcnow().isoformat() + "Z"
    profile["_raw"] = raw_sections   # keep raw for future re-synthesis
    save_profile(profile)

    briefing = _build_briefing(profile)
    return briefing, profile


def _build_briefing(profile: dict) -> str:
    lines = ["# Environment briefing\n"]

    summary = profile.get("summary", "")
    if summary:
        lines.append(summary + "\n")

    guests = profile.get("guests", [])
    if guests:
        running = [g for g in guests if g.get("status") == "running"]
        lines.append(
            f"**{len(guests)} guests** ({len(running)} running) · "
            f"PVE {profile.get('pve_version', '?')} · "
            f"Backup: {profile.get('backup_health', '?')} · "
            f"Security: {profile.get('security_posture', '?')} · "
            f"Patches: {profile.get('patch_status', '?')}\n"
        )

    items = profile.get("action_items", [])
    if items:
        lines.append("## Prioritised action items\n")
        for item in items:
            sev   = item.get("severity", "INFO")
            title = item.get("title", "")
            detail = item.get("detail", "")
            tool_  = item.get("tool")
            badge  = f"[{sev}]"
            lines.append(f"**{badge} {title}**")
            if detail:
                lines.append(f"  {detail}")
            if tool_:
                lines.append(f"  → `{tool_}`")
            lines.append("")

    lines.append("---")
    lines.append("Type a request or question to continue. The agent has full tool access.")
    return "\n".join(lines)


def profile_to_context(profile: dict) -> str:
    """Return a compact context string to inject into the system prompt."""
    if not profile:
        return ""
    items = profile.get("action_items", [])
    top_items = "\n".join(
        f"  - [{i.get('severity')}] {i.get('title')}" for i in items[:5]
    )
    guests = profile.get("guests", [])
    guest_list = ", ".join(
        f"{g.get('name')} ({g.get('type')})" for g in guests if g.get("status") == "running"
    )
    return f"""
## Known environment (from last scan {profile.get('profile_date', '?')[:10]})
Node: {profile.get('node_name', 'pve')}  |  PVE: {profile.get('pve_version', '?')}
Running guests: {guest_list}
Backup health: {profile.get('backup_health', '?')}  |  Security: {profile.get('security_posture', '?')}  |  Patches: {profile.get('patch_status', '?')}
Open action items:
{top_items}
""".strip()
