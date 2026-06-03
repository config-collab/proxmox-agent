"""
Proxmox management agent — session entrypoint.

Modes:
  python main.py               # interactive LLM assistant (auto-onboards on first run)
  python main.py --no-llm      # headless: run inventory + print, then exit (cron/LXC use)
  python main.py --rediscover  # force re-run full discovery even if profile exists
  python main.py --all-tools   # always send all 6 tool schemas (disables routing)
  python main.py --node <name> # target a specific PVE node (default: pve)
"""
import argparse
import datetime
import os
import config   # loads .env
import audit
import llm
import tools    # registers all @tool decorators
import onboarding
import tokens


# ── System prompt ──────────────────────────────────────────────────────────────
# Kept deliberately short — every token here is paid on every request.
# CRITICAL: This agent is a decision-support tool, NOT autonomous. User is responsible.

BASE_SYSTEM_PROMPT = """\
**You are a Proxmox decision-support assistant, not an autonomous agent.**

CRITICAL DISCLAIMERS:
- You CANNOT learn from mistakes during execution. If you misunderstand a situation, \
that error is final until the user corrects it.
- You have NO real-time awareness of what your tools actually do—you read their output \
after the fact. This creates a "blindness window" where a tool could fail silently.
- For ANY destructive operation (patches, deletes, config changes), \
the user must verify your reasoning first via: ask_community(), show_reasoning(), \
or audit_log_export().
- If you ever say "this is safe", you are WRONG. Infrastructure decisions are never safe \
without human verification.

YOUR ROLE:
1. Query the environment to understand its state
2. Propose actions with explicit reasoning (show your sources: docs, community, audit log)
3. Require user confirmation before ANYTHING irreversible
4. Log every operation for audit
5. Surface uncertainty—if you're unsure, say so loudly

TOOLS YOU HAVE (24 total):
- Inventory: get_inventory, get_metrics, get_tasks
- Patching: check_patches, apply_patches (NEEDS USER CONFIRMATION)
- Backup: check_backups, check_pbs, run_backup_now, pbs_maintenance
- VMs: manage_vm, manage_snapshots, create_container
- Security: security_audit, search_cve
- Docs: search_docs, search_forum, search_helper_scripts, search_environment
- Community: ask_community, trending_proxmox (Reddit—user sees actual discussions)
- Transparency: show_reasoning, audit_log_export, compare_with_community
- Guards: check_pve_protection, test_guard (host protection)
- Refresh: refresh_environment_knowledge

RULES:
✓ Dry-run ALL patches by default (require dry_run=false to execute)
✓ Snapshot before any write (unless user disabled it)
✓ Check PVE protection before host changes
✓ Log every decision: user can export full audit trail
✓ When uncertain, consult ask_community() before recommending
✓ Never say "this is safe"—say "I recommend verifying via [method]"

Current Proxmox host: {host}
{env_context}"""


def build_system_prompt(profile: dict | None) -> str:
    env_ctx = onboarding.profile_to_context(profile) if profile else ""
    return BASE_SYSTEM_PROMPT.format(host=config.PROXMOX_HOST, env_context=env_ctx).strip()


def _seed_message(content: str) -> dict:
    """Mark a message as the system seed so trim_history never drops it."""
    return {"role": "user", "content": content, "_system_seed": True}


# ── Modes ──────────────────────────────────────────────────────────────────────

def run_headless(node: str):
    print(f"[proxmox-agent] headless — node: {node}")

    inv = tools.dispatch("get_inventory", {"node": node})
    print(inv)
    audit.log("session.headless", node, outcome="ok", reversible=True)

    # Security + patch scan to power ntfy alerts
    findings_summary = []
    try:
        sec = tools.dispatch("security_audit", {"host_only": True})
        crits = sec.count("[CRITICAL]")
        highs = sec.count("[HIGH]")
        if crits or highs:
            findings_summary.append(f"{crits} critical, {highs} high security findings")
    except Exception as exc:
        print(f"  [security scan failed] {exc}")

    try:
        pat = tools.dispatch("check_patches", {})
        if "security" in pat.lower() and "pending" in pat.lower():
            import re
            m = re.search(r"(\d+)\s+security", pat)
            if m:
                findings_summary.append(f"{m.group(1)} security patches pending")
    except Exception as exc:
        print(f"  [patch scan failed] {exc}")

    if findings_summary:
        _notify(f"Proxmox agent alert — {node}", " · ".join(findings_summary))

    audit.flush()


def _notify(title: str, message: str):
    """Send a push notification via ntfy.sh if NTFY_URL is configured."""
    url = os.environ.get("NTFY_URL", "").strip()
    if not url:
        return
    import urllib.request
    try:
        data = f"{title}\n{message}".encode()
        headers = {"Title": title, "Priority": "high", "Tags": "warning"}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=5)
        print(f"  [ntfy] alert sent to {url}")
    except Exception as exc:
        print(f"  [ntfy] send failed: {exc}")


def run_interactive(node: str, force_rediscover: bool = False, all_tools: bool = False):
    provider = os.environ.get("LLM_PROVIDER", "claude")
    print(f"[proxmox-agent] starting — provider: {provider}  node: {node}")

    # ── Onboarding / profile ───────────────────────────────────────────────────
    profile = onboarding.load_profile()

    if onboarding.is_first_run() or force_rediscover:
        print("\nFirst run detected — running full environment discovery.")
        print("This will take about 60 seconds and will not make any changes.\n")
        briefing, profile = onboarding.run_discovery(node=node)
        print("\n" + "=" * 70)
        print(briefing)
        print("=" * 70 + "\n")
    else:
        age_days = _profile_age_days(profile)
        age_msg  = f" (profile {age_days}d old)" if age_days is not None else ""
        print(f"[profile loaded{age_msg}]")
        if age_days is not None and age_days > 7:
            print(f"  Tip: profile is {age_days} days old — run with --rediscover to refresh")

    # ── Build conversation ─────────────────────────────────────────────────────
    system_prompt = build_system_prompt(profile)
    messages: list[dict] = [_seed_message(system_prompt)]

    # Seed with a compact startup inventory — full output shown to user, compact stored
    print("Pulling live inventory snapshot ...\n")
    inv = tools.dispatch("get_inventory", {"node": node})
    audit.log("get_inventory", node, outcome="ok", reversible=True)
    messages.append({"role": "assistant", "content": tokens.compact(inv)})
    print(inv)
    print("\n" + "─" * 70 + "\n")
    print("Assistant ready. Type a request or question. Ctrl-C / 'exit' to quit.\n")

    tool_schemas = tools.all_schemas()

    # ── Chat loop ──────────────────────────────────────────────────────────────
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[session end]")
            break

        if not user_input or user_input.lower() in ("exit", "quit"):
            print("[session end]")
            break

        if user_input.lower() in ("rediscover", "/rediscover"):
            print("Re-running full discovery ...")
            briefing, profile = onboarding.run_discovery(node=node)
            messages = [{"role": "user", "content": build_system_prompt(profile)}]
            print(briefing)
            continue

        messages.append({"role": "user", "content": user_input})

        # Agentic loop — LLM calls tools until it produces a final text response
        while True:
            active  = tokens.trim_history(messages)
            schemas = tool_schemas if all_tools else tokens.route_schemas(user_input, tool_schemas)

            try:
                text, tool_calls = llm.chat(active, schemas)
            except Exception as exc:
                print(f"[LLM error] {exc}")
                break

            if tool_calls:
                assistant_msg = llm.assistant_tool_call_message(text, tool_calls)
                if assistant_msg:
                    messages.append(assistant_msg)
                if text:
                    print(f"Assistant: {text}")

                for tc in tool_calls:
                    print(f"\n[tool] {tc['name']}({_fmt_inputs(tc['input'])})")
                    result = tools.dispatch(tc["name"], tc["input"])
                    audit.log(tc["name"], str(tc["input"]), outcome="ok", reversible=True)
                    print(result)
                    # Display: full output. LLM history: compact
                    messages.append(llm.tool_result_message(tc["id"], tokens.compact(result)))
                continue

            if text:
                print(f"\nAssistant: {text}\n")
                messages.append({"role": "assistant", "content": text})
            break

    audit.flush()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _profile_age_days(profile: dict | None) -> int | None:
    if not profile:
        return None
    try:
        ts = profile.get("profile_date", "")
        if not ts:
            return None
        dt = datetime.datetime.fromisoformat(ts.rstrip("Z")).replace(
            tzinfo=datetime.timezone.utc
        )
        return (datetime.datetime.now(datetime.timezone.utc) - dt).days
    except Exception:
        return None


def _fmt_inputs(inputs: dict) -> str:
    if not inputs:
        return ""
    return ", ".join(f"{k}={v!r}" for k, v in inputs.items())


# ── Entrypoint ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Proxmox management agent")
    parser.add_argument("--no-llm",     action="store_true", help="Headless mode — print inventory and exit")
    parser.add_argument("--rediscover", action="store_true", help="Force full environment re-discovery")
    parser.add_argument("--all-tools",  action="store_true", help="Always send all tool schemas (disables routing)")
    parser.add_argument("--node",       default="pve",       help="PVE node name (default: pve)")
    args = parser.parse_args()

    if args.no_llm:
        run_headless(args.node)
    else:
        run_interactive(args.node, force_rediscover=args.rediscover, all_tools=args.all_tools)


if __name__ == "__main__":
    main()
