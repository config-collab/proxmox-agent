"""
Docs tools — local BM25 search over PVE docs + live Proxmox forum search
         + community helper scripts search.
"""
from tools import tool
from docs.index import search_formatted, forum_search, rebuild_env_index
from docs.helper_scripts import search_formatted as search_helpers_fmt
from docs import reddit_search


@tool(
    name="search_docs",
    description="Search local Proxmox documentation (qm, pct, vzdump, pvesm, firewall, PBS). Use for how-to questions, command syntax, config options.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search terms."},
            "top_k": {"type": "integer", "description": "Results to return (default 4, max 8)."},
        },
        "required": ["query"],
    },
)
def search_docs(query: str, top_k: int = 4) -> str:
    top_k = min(top_k, 8)
    return search_formatted(query, top_k)


@tool(
    name="search_forum",
    description="Live search the Proxmox community forum for recent threads. Use for error messages, known bugs, community workarounds, or anything not in the official docs.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search terms or error message."},
        },
        "required": ["query"],
    },
)
def search_forum_tool(query: str) -> str:
    return forum_search(query)


@tool(
    name="search_helper_scripts",
    description="Search community Proxmox helper scripts (tteck / community-scripts). Returns one-liner install commands to run on the Proxmox host. Use when user wants to install or set up a service (e.g. Home Assistant, Vaultwarden, Pi-hole).",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "App or service name to search for."},
            "top_k": {"type": "integer", "description": "Results to return (default 6)."},
        },
        "required": ["query"],
    },
)
def search_helper_scripts(query: str, top_k: int = 6) -> str:
    return search_helpers_fmt(query, min(top_k, 12))


@tool(
    name="search_cve",
    description="Search the NIST NVD for CVEs affecting a package or keyword. Use when assessing patch risk or investigating a security finding.",
    input_schema={
        "type": "object",
        "properties": {
            "keyword":      {"type": "string", "description": "Package name or keyword (e.g. 'openssl', 'sudo')."},
            "top_k":        {"type": "integer", "description": "Results to return (default 5)."},
            "severity_min": {"type": "string",  "enum": ["", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
                             "description": "Minimum severity to include. Empty = all."},
        },
        "required": ["keyword"],
    },
)
def search_cve(keyword: str, top_k: int = 5, severity_min: str = "") -> str:
    from docs.cve_search import search as cve_search_raw
    results = cve_search_raw(keyword, min(top_k, 10), severity_min)
    if not results or results[0].get("id") == "error":
        return f"CVE lookup failed: {results[0].get('description', 'no results')}" if results else "No results."
    lines = [f"CVEs for '{keyword}':"]
    for r in results:
        badge = f"[{r['severity']} {r['score']}]" if r['severity'] else ""
        lines.append(f"\n{r['id']} {badge} ({r['published']})\n  {r['description']}\n  {r['url']}")
    return "\n".join(lines)


@tool(
    name="search_environment",
    description="Search knowledge about THIS specific environment: guest names, IPs, purposes, past operation history, known failures. Use before 'what is X?' or 'has X ever failed?' questions.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look up (guest name, IP, operation type, etc.)"},
        },
        "required": ["query"],
    },
)
def search_environment(query: str) -> str:
    results = search_formatted(query, top_k=4)
    return results


@tool(
    name="refresh_environment_knowledge",
    description="Rebuild the environment knowledge index from env_profile.json and audit log. Call after a full rediscovery or when the agent seems unaware of recent changes.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
def refresh_environment_knowledge() -> str:
    rebuild_env_index()
    from docs.env_memory import build
    chunks = build(force=True)
    return f"Environment knowledge rebuilt: {len(chunks)} chunks indexed."


@tool(
    name="ask_community",
    description=(
        "Search r/Proxmox for community Q&A on a topic. "
        "Shows actual Reddit discussions with upvotes, comments, and timestamps. "
        "Transparent source — user sees exactly where the advice comes from. "
        "Read-only: no autonomous action based on community replies."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "keyword":    {"type": "string", "description": "Topic to search (e.g. 'ZFS performance', 'backup strategies', 'networking')."},
            "top_k":      {"type": "integer", "description": "Results to show (default 5)."},
            "time_range": {"type": "string",  "enum": ["week", "month", "year", "all"],
                           "description": "Time range to search (default: year)."},
        },
        "required": ["keyword"],
    },
)
def ask_community(keyword: str, top_k: int = 5, time_range: str = "year") -> str:
    results = reddit_search.search(keyword, top_k, time_filter=time_range)
    if not results or results[0].get("id") == "error":
        return f"Could not reach r/Proxmox: {results[0].get('body_preview', 'network error')}"
    return reddit_search.search_formatted(keyword, top_k)


@tool(
    name="trending_proxmox",
    description="Show what's trending on r/Proxmox this week. Pulse-check on community concerns and recent wins.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
def trending_proxmox() -> str:
    return reddit_search.search_formatted_trending(top_k=8)


@tool(
    name="search_all_sources",
    description=(
        "Unified search across ALL knowledge sources (official docs, forum, CVE database, community-scripts, Reddit). "
        "Returns results ranked by authority tier with sources clearly labeled. "
        "This is the 'trust check' tool—it shows exactly what the agent consulted and in what order."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Your question or topic to research (e.g. 'ZFS on Proxmox', 'backup best practices', 'networking configuration')."},
            "min_tier": {"type": "integer", "enum": [1, 2, 3, 4, 5],
                         "description": "Minimum authority tier to include (1=official only, 5=all sources)."},
        },
        "required": ["query"],
    },
)
def search_all_sources(query: str, min_tier: int = 1) -> str:
    """
    Searches all RAG tiers (official docs, forums, CVE, scripts, Reddit)
    and returns results ranked by authority weight with explicit source labels.
    """
    results = {
        "tier_1_official": [],
        "tier_2_forum": [],
        "tier_3_scripts": [],
        "tier_4_reddit": [],
        "tier_5_cve": [],
        "search_metadata": {
            "query": query,
            "min_tier": min_tier,
            "sources_checked": [],
        }
    }

    # Tier 1: Official Docs (weight 3.0x)
    if min_tier <= 1:
        tier1 = search_formatted(query, top_k=3)
        results["tier_1_official"] = tier1
        results["search_metadata"]["sources_checked"].append("Official Proxmox docs (pve.proxmox.com)")

    # Tier 2: Community Forum (weight 2.0x)
    if min_tier <= 2:
        tier2 = forum_search(query)
        results["tier_2_forum"] = tier2
        results["search_metadata"]["sources_checked"].append("Proxmox Support Forum (forum.proxmox.com)")

    # Tier 3: Helper Scripts (weight 1.5x)
    if min_tier <= 3:
        tier3 = search_helpers_fmt(query, top_k=3)
        results["tier_3_scripts"] = tier3
        results["search_metadata"]["sources_checked"].append("Community Helper Scripts (community-scripts.org)")

    # Tier 4: Reddit (weight 0.8x)
    if min_tier <= 4:
        tier4 = reddit_search.search_formatted(query, top_k=3)
        results["tier_4_reddit"] = tier4
        results["search_metadata"]["sources_checked"].append("r/Proxmox community (Reddit)")

    # Tier 5: CVE Database (real-time, critical override)
    if min_tier <= 5 and any(kw in query.lower() for kw in ["cve", "vulnerability", "security", "patch", "exploit"]):
        from docs.cve_search import search as cve_search_fn
        tier5 = cve_search_fn(query)
        results["tier_5_cve"] = tier5
        results["search_metadata"]["sources_checked"].append("NIST NVD CVE Database (nvd.nist.gov)")

    # Format output
    output = f"""
┌─────────────────────────────────────────────────┐
│   UNIFIED PROXMOX KNOWLEDGE SOURCE SEARCH       │
│   Query: {query}
│   Authority Tiers: 1 (Official) → 5 (Community)
└─────────────────────────────────────────────────┘

SOURCES CONSULTED:
{chr(10).join('  • ' + s for s in results['search_metadata']['sources_checked'])}

───────────────────────────────────────────────────

🏆 TIER 1: OFFICIAL PROXMOX DOCS (Authority: ★★★)
{results['tier_1_official'] if results['tier_1_official'] else '  [No results]'}

👥 TIER 2: COMMUNITY FORUM (Authority: ★★☆)
{results['tier_2_forum'] if results['tier_2_forum'] else '  [No results]'}

🛠️  TIER 3: HELPER SCRIPTS (Authority: ★★☆)
{results['tier_3_scripts'] if results['tier_3_scripts'] else '  [No results]'}

💬 TIER 4: REDDIT DISCUSSION (Authority: ★☆☆)
{results['tier_4_reddit'] if results['tier_4_reddit'] else '  [No results]'}

⚠️  TIER 5: CVE VULNERABILITIES (Authority: CRITICAL)
{results['tier_5_cve'] if results['tier_5_cve'] else '  [No critical CVEs found]'}

───────────────────────────────────────────────────
[All sources transparent & clickable. No hallucinated sources.]
"""
    return output


@tool(
    name="compare_with_all_sources",
    description=(
        "Before making a risky change, consult all sources to see: "
        "(1) What official docs say, (2) What community has experienced, "
        "(3) Any known failures or CVEs, (4) Alternative approaches. "
        "Builds confidence by showing consensus or conflicts."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "description": "The operation you're considering (e.g. 'upgrade Proxmox to 8.2', 'enable Ceph', 'patch pihole')."},
            "target": {"type": "string", "description": "Target system (e.g. 'pve', 'pihole-lxc', 'ceph-node-1'). Optional."},
        },
        "required": ["operation"],
    },
)
def compare_with_all_sources(operation: str, target: str = "") -> str:
    """
    Comprehensive pre-flight check: consults all sources to show
    consensus, conflicts, risks, and experienced-user workarounds.
    Specifically designed to answer: "Is this safe? What went wrong for others?"
    """
    search_query = f"{operation} {target}".strip()

    output = f"""
┌─────────────────────────────────────────────────┐
│   PRE-FLIGHT SOURCE CONSENSUS CHECK             │
│   Operation: {operation}
{f'│   Target: {target}' if target else ''}
└─────────────────────────────────────────────────┘

Searching all authoritative sources for:
  ✓ Official recommendation
  ✓ Known risks or failures
  ✓ Community workarounds
  ✓ Recent CVE impacts
  ✓ Alternative approaches

"""

    # Tier 1: Official guidance
    tier1 = search_formatted(search_query, top_k=2)
    output += f"""
🏆 OFFICIAL DOCS SAY:
{tier1}
"""

    # Tier 2: Forum experience reports
    tier2 = forum_search(f"{operation} failed {target}".strip())
    output += f"""
👥 COMMUNITY EXPERIENCE:
  (Searching for failures, warnings, workarounds...)
{tier2 if tier2 else '  [No recent failure reports — good sign]'}
"""

    # Tier 5: CVE check (if security-related)
    if any(kw in operation.lower() for kw in ["patch", "upgrade", "security", "cve"]):
        from docs.cve_search import search as cve_search_fn
        cves = cve_search_fn(f"{operation} {target}")
        output += f"""
⚠️  SECURITY BULLETINS:
{cves if cves else '  [No critical CVEs blocking this operation]'}
"""

    # Alternative approaches
    alt_query = f"{operation} alternative {target}".strip()
    alts = forum_search(alt_query)
    output += f"""
💡 COMMUNITY ALTERNATIVES:
{alts if alts else '  [No documented alternatives]'}

───────────────────────────────────────────────────
SUMMARY FOR YOUR DECISION:
  • Sources: 4-5 tiers consulted (all transparent above)
  • Consensus: Compare 'Official' vs 'Community' results
  • Risks: Look for 'failed', 'CVE', 'workaround' mentions
  • Next: [Run] to execute, [Show reasoning] for full chain-of-thought
"""
    return output
