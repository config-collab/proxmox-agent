"""
Token-budget utilities.

compact(text)              — strips markdown, tables → CSV, collapses whitespace (~65% saving)
trim_history(msgs)         — rolling window: keeps system seed + last MAX_TURNS pairs
summarise_old(msgs)        — summarises dropped turns into a single injected message
route_schemas(msg, schemas) — returns only the tool schemas relevant to the user's message
                              Saves ~80-450 tokens/request by excluding unneeded schemas.
                              Falls back to all schemas if intent is ambiguous.
"""
import re

# Max user+assistant turn pairs to keep in active context.
# Each pair ≈ 200-600 tokens depending on tool call density.
MAX_TURNS = 8


# ── Compact renderer ───────────────────────────────────────────────────────────

def compact(text: str, max_chars: int = 2000) -> str:
    """
    Convert Markdown tool output to a dense plain-text form for LLM history.

    Transformations:
      Markdown tables   → header row + CSV data rows
      ## headers        → stripped (LLM doesn't need decorative structure)
      **bold**          → plain text
      `code`            → plain text
      blank lines (2+)  → single newline
      leading spaces    → stripped per line
    """
    if not text:
        return ""

    lines = text.splitlines()
    out: list[str] = []
    in_table = False
    table_headers: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Skip pure-markdown decoration
        if re.match(r"^#{1,4}\s", stripped):
            # Keep the heading text, drop the # prefix
            out.append(re.sub(r"^#{1,4}\s+", "", stripped))
            continue

        if re.match(r"^\|[-| ]+\|$", stripped):
            # Separator row in a table — skip
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                # First row = headers
                table_headers = cells
                in_table = True
                out.append(",".join(table_headers))
            else:
                out.append(",".join(cells))
            continue

        in_table = False
        table_headers = []

        # Strip inline markdown
        stripped = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)   # bold
        stripped = re.sub(r"\*(.+?)\*",     r"\1", stripped)   # italic
        stripped = re.sub(r"`(.+?)`",       r"\1", stripped)   # inline code
        stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)  # links
        stripped = re.sub(r"^>\s*",         "",    stripped)   # blockquotes

        if stripped:
            out.append(stripped)

    result = "\n".join(out)
    # Collapse 2+ blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)

    if len(result) > max_chars:
        result = result[:max_chars] + f"\n...[truncated, {len(result)-max_chars} chars omitted]"

    return result.strip()


# ── Message history management ─────────────────────────────────────────────────

def _is_system_seed(msg: dict) -> bool:
    """The first user message is the system prompt seed — never drop it."""
    return msg.get("role") == "user" and msg.get("_system_seed", False)


def _count_turns(messages: list[dict]) -> int:
    """Count user+assistant pairs after the system seed."""
    turns = 0
    for m in messages[1:]:
        if m.get("role") == "user":
            turns += 1
    return turns


def trim_history(messages: list[dict], max_turns: int = MAX_TURNS) -> list[dict]:
    """
    Keep the system seed + the most recent max_turns turns.
    One turn = one user message + all subsequent messages until the next user message
    (including tool calls and results).

    Also compresses any tool_result content still in the window.
    """
    if not messages:
        return messages

    seed = messages[0]

    # Group messages after the seed into turns.
    # A new turn begins at each user message.
    turns: list[list[dict]] = []
    current: list[dict] = []
    for msg in messages[1:]:
        if msg.get("role") == "user" and current:
            turns.append(current)
            current = [msg]
        else:
            current.append(msg)
    if current:
        turns.append(current)

    kept_turns = turns[-max_turns:]
    kept = [msg for turn in kept_turns for msg in turn]

    result = [seed] + kept

    # Compress any tool result content still in the window
    result = [
        {**m, "content": compact(m["content"])}
        if m.get("role") == "tool" and isinstance(m.get("content"), str)
        else m
        for m in result
    ]
    return result


def summarise_dropped(dropped: list[dict]) -> dict | None:
    """
    Build a brief summary message for turns that were dropped from the window.
    Injected as a user message so the LLM retains memory of what happened.
    """
    if not dropped:
        return None

    tool_calls_seen: list[str] = []
    for msg in dropped:
        # Anthropic format
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls_seen.append(block.get("name", "?"))
        # OpenAI format
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tool_calls_seen.append(tc.get("function", {}).get("name", "?"))

    if not tool_calls_seen:
        return None

    unique = list(dict.fromkeys(tool_calls_seen))   # deduplicate, preserve order
    summary = f"[Earlier in this session the following tools were called: {', '.join(unique)}. Results are no longer in context — re-call if needed.]"
    return {"role": "user", "content": summary}


# ── Schema routing ─────────────────────────────────────────────────────────────
# Maps keywords in user messages to the tool names they imply.
# Multiple tools per keyword is fine — they're unioned together.

_ROUTES: dict[str, list[str]] = {
    # Inventory / status
    "inventory":  ["get_inventory"],
    "running":    ["get_inventory"],
    "list":       ["get_inventory"],
    "what":       ["get_inventory"],
    "show":       ["get_inventory"],
    "status":     ["get_inventory"],
    "guest":      ["get_inventory"],
    "vm":         ["get_inventory"],
    "lxc":        ["get_inventory"],
    "container":  ["get_inventory"],
    "storage":    ["get_inventory"],

    # Patches / updates
    "patch":      ["check_patches", "apply_patches"],
    "update":     ["check_patches", "apply_patches"],
    "upgrade":    ["check_patches", "apply_patches"],
    "outdated":   ["check_patches"],
    "behind":     ["check_patches"],
    "apt":        ["check_patches", "apply_patches"],
    "package":    ["check_patches"],
    "apply":      ["apply_patches"],
    "install":    ["apply_patches"],

    # Backups
    "backup":     ["check_backups", "check_pbs"],
    "restore":    ["check_backups"],
    "recovery":   ["check_backups"],
    "rpo":        ["check_backups"],
    "backed":     ["check_backups"],
    "archive":    ["check_backups", "check_pbs"],
    "retention":  ["check_backups"],
    "vzdump":     ["check_backups"],

    # PBS-specific
    "pbs":        ["check_pbs"],
    "snapshot":   ["check_pbs"],
    "verify":     ["check_pbs"],
    "verificat":  ["check_pbs"],
    "gc":         ["check_pbs"],
    "garbage":    ["check_pbs"],
    "datastore":  ["check_pbs"],
    "prune":      ["check_pbs"],

    # Docs / forum
    "how":        ["search_docs"],
    "what is":    ["search_docs"],
    "syntax":     ["search_docs"],
    "command":    ["search_docs"],
    "config":     ["search_docs"],
    "option":     ["search_docs"],
    "flag":       ["search_docs"],
    "document":   ["search_docs"],
    "manual":     ["search_docs"],
    "error":      ["search_docs", "search_forum"],
    "failed":     ["search_docs", "search_forum"],
    "forum":      ["search_forum"],
    "community":  ["search_forum"],
    "workaround": ["search_forum"],
    "issue":      ["search_forum"],
    "bug":        ["search_forum"],

    # Security
    "secur":      ["security_audit", "check_patches"],
    "harden":     ["security_audit"],
    "audit":      ["security_audit"],
    "firewall":   ["security_audit"],
    "port":       ["security_audit"],
    "ssh":        ["security_audit"],
    "tls":        ["security_audit"],
    "cert":       ["security_audit"],
    "cve":        ["security_audit", "check_patches"],
    "vulnerab":   ["security_audit", "check_patches"],
    "expos":      ["security_audit"],
    "open port":  ["security_audit"],
}

# Minimum number of distinct tool names that must match before we
# trust the routing. Below this threshold we fall back to all schemas.
_MIN_ROUTE_CONFIDENCE = 1


def route_schemas(user_message: str, all_schemas: list[dict]) -> list[dict]:
    """
    Return only the tool schemas relevant to user_message.
    Falls back to all_schemas when intent is unclear (short/ambiguous input).

    Saves 80-450 tokens per request when the user's intent is focused.
    """
    import re as _re
    msg   = user_message.lower()
    words = msg.split()
    # Word-level token set for precise matching (avoids "all" matching "firewall")
    tokens_set = set(_re.findall(r"[a-z0-9]+", msg))

    matched: set[str] = set()
    for keyword, tool_names in _ROUTES.items():
        if " " in keyword:
            # Multi-word keyword: substring match is fine
            if keyword in msg:
                matched.update(tool_names)
        else:
            # Single-word keyword: prefix match against each token in the message
            # e.g. "patch" matches "patches", "secur" matches "security"
            if any(tok.startswith(keyword) for tok in tokens_set):
                matched.update(tool_names)

    # Fallback: too short, or genuinely general question
    # Note: "check" intentionally excluded — "check patches" is a specific intent
    _GENERAL_WORDS = {"everything", "all", "full", "overview", "health"}
    is_general = bool(tokens_set & _GENERAL_WORDS)
    if len(words) <= 2 or is_general or len(matched) < _MIN_ROUTE_CONFIDENCE:
        return all_schemas

    schema_map = {s["name"]: s for s in all_schemas}
    routed = [schema_map[name] for name in matched if name in schema_map]

    # Always keep get_inventory in context — it's cheap (no params) and the LLM
    # often needs it as a prerequisite to answer questions about specific guests.
    inv_schema = schema_map.get("get_inventory")
    if inv_schema and inv_schema not in routed:
        routed.insert(0, inv_schema)

    return routed


def route_token_saving(user_message: str, all_schemas: list[dict]) -> str:
    """Human-readable report of what routing would select — useful for debugging."""
    routed = route_schemas(user_message, all_schemas)
    all_names    = [s["name"] for s in all_schemas]
    routed_names = [s["name"] for s in routed]
    dropped      = [n for n in all_names if n not in routed_names]
    # Rough token estimate: avg schema ~95 tokens after tightening
    saved = len(dropped) * 95
    return (
        f"Routing '{user_message[:40]}': "
        f"using {routed_names}, dropping {dropped} (~{saved} tokens saved)"
    )
