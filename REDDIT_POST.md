# Reddit Post: Proxmox AI Agent – From CAD/PDM to Infrastructure

## Title (r/Proxmox)
**"I built an AI agent for Proxmox inspired by how CAD/PDM replaced complex GUIs—but with security by design"**

---

## Post Body

Coming from an engineering background (CAD, PDM systems), I've seen how AI replaced 10-click workflows with conversational interfaces. But infrastructure is different—a wrong change can break your homelab. So I built a Proxmox agent that **replaces GUI complexity with AI, but you stay in control**.

### The Problem

Proxmox UI requires:
- Click Datacenter → Permissions → API Tokens → Add...
- Navigate Storage → Content → Upload ISO
- Search logs across VMs
- Trial-and-error snapshots
- Manual patch sequencing

**What if you could just ask:** *"Are my backups healthy? Patch pihole if safe. Run a security audit."*

The Reddit pushback I expected: *"AI will hallucinate and break my host."* Fair point. So this isn't autonomous—it's **decision-support with hard security boundaries**.

---

## How It's Different: Security by Design

### 1. You Approve Every Write
```
Default mode: "Suggest" (Level 1)
Agent proposes → Shows dry-run → You click [Run]
Nothing happens without your explicit approval
```

Not "autonomous agent that learns from mistakes"—you see the reasoning before it acts.

### 2. Multi-Source Verification (Not Reddit Alone)
The agent searches:
- **Tier 1:** Official Proxmox docs (pve.proxmox.com) — ground truth
- **Tier 2:** Proxmox forums (moderated by Proxmox staff) — peer-verified
- **Tier 3:** Community scripts + helper repos
- **Tier 4:** Reddit (lowest priority, sentiment only)
- **Tier 5:** Real-time CVE database (critical override)

Every recommendation shows which sources it consulted. You can click and verify.

### 3. Host Protection (Can't Accidentally Break PVE)
Three modes:
- **Strict (default):** Proxmox host writes blocked entirely
- **Warn:** Allowed but requires pre-flight PBS backup first
- **Off:** Only for dev/test nodes

### 4. Full Audit Trail
```json
{
  "timestamp": "2026-06-03T14:32:15Z",
  "operation": "apply_patches",
  "target": "pihole-lxc",
  "sources_consulted": [
    "pve.proxmox.com:pve-docs/chapter-patching.html",
    "forum.proxmox.com/threads/pihole-patches-12345",
    "nvd.nist.gov/vuln/detail/CVE-2024-..."
  ],
  "reasoning_chain": [
    "Official docs recommend monthly patching",
    "Forum consensus: no recent failures",
    "CVE check: 0 critical, 1 medium fixed in next version"
  ],
  "action": "executed",
  "result": "12 packages updated, 0 failures",
  "reversible": true,
  "rollback_available": "snapshot-pihole-20260603-143200"
}
```

Every change is logged. You can export and share if something breaks (community can help because they see the full decision chain).

### 5. Autonomy Levels (Progressive Trust)
- **Level 0 (Observe):** Read-only. Agent can only query and suggest.
- **Level 1 (Suggest):** Draft → you approve each action [default]
- **Level 2 (Maintain):** Auto-patch guests (not host). Pre-flight snapshots.
- **Level 3 (Full):** Autonomous (dev/test only, high risk)

Start at Level 1. Graduate to Level 2 after you've verified the agent's judgment. Never touch Level 3 in production.

---

## What I'm Solving

| GUI | Agent |
|-----|-------|
| Click Datacenter → Permissions → API Tokens | `openSettings()` and copy token (1 click) |
| Search guest logs across 5 VMs | `"what errors in the past 24h?"` |
| Manual: qm set vm100 --memory 4096 | `"pihole is hitting 100% RAM, add 2GB"` |
| Trial-and-error snapshots | `"test this patch safely"` (auto-snapshots) |
| r/Proxmox thread search (45 min) | `"ask_community('backup strategy')"` (2 sec) |

### Real Example Flow

```
User: "patch pihole and check backups"

Agent:
  ✓ Consulting official Proxmox docs...
  ✓ Searching forum for pihole patch issues...
  ✓ Checking CVE database...
  ✓ Looking at your environment...
  
  Dry-run patches: apt update && apt upgrade
  Forum consensus: 0 recent failures
  CVEs: 1 medium-severity, fix available
  Your snapshot: ready
  
  [Run] [Show reasoning] [Ask community]
  
User clicks [Run]
  → Pre-flight snapshot created
  → Patches applied
  → Backups checked (last: 4h ago, healthy)
  → Full audit log created
  
Agent: "✓ Patched 12 packages. Backups healthy. Rollback available for 24h."
```

---

## Addressing the Skeptics

**"AI will hallucinate."**
- Consulted 5 tiers of sources (docs + forums + CVE + Reddit)
- Shows reasoning chain
- You approve before it runs
- Audit trail if something breaks

**"When it breaks, nobody will help."**
- Full decision log shows what sources were consulted
- Reasoning explains why the agent thought it was safe
- Community can debug from audit trail
- Snapshot rollback available

**"I don't trust AI agents."**
- Not autonomous—it's a decision-support tool
- Default mode requires your approval for every action
- Host protection prevents accidental PVE breakage
- Like CAD PDM: replaces clicks, not responsibility

---

## What This Enables

1. **Maintenance on schedule, not when you remember**
   - Cron job: 2am inventory + patch check
   - 3am security audit
   - Agent reports findings, awaits approval

2. **Infrastructure-as-conversation**
   - "Create an LXC for Home Assistant"
   - "Diagnose the network issue"
   - "Compare my setup against Proxmox best practices"

3. **Community knowledge at your fingertips**
   - "Ask r/Proxmox about Ceph reliability"
   - "Find helper scripts for Vaultwarden"
   - "Check if anyone else hit this CVE on Ryzen 7950X"

4. **Audit trail for learning**
   - Every change logged with reasoning
   - Replay decisions to understand "why did the agent patch this?"
   - Export to share with team or for incident response

---

## The Tech (For Engineers)

- **Architecture:** FastAPI + vanilla JS + SSE streaming (real-time UI)
- **RAG:** BM25 keyword search over official docs + environment state + CVE database
- **LLM:** Claude with extended thinking for patch safety assessment
- **Tools:** 26 integrated (inventory, patch, backup, networking, snapshots, CVE lookup, Reddit search, etc.)
- **Storage:** JSONL audit logs, snapshots for rollback, PBS for incremental backups
- **Deployment:** Lightweight LXC (150MB) or direct on Pi/BananaPi, or standalone on Proxmox host

---

## Security Checklist

- [x] Conservative defaults (read-only by default)
- [x] Multi-source verification (official > forums > Reddit)
- [x] Pre-flight backups (snapshots + PBS)
- [x] Host protection (can't touch PVE without explicit permission)
- [x] Approval workflow (nothing runs without you clicking)
- [x] Full audit trail (every decision logged + exportable)
- [x] Rollback available (snapshots + PBS restore)
- [x] Community-verifiable (reasoning shown, sources cited)

---

## Why This Matters

In CAD/PDM world: replacing File → Save As → versioning with "save" = obvious win.

In infrastructure: replacing "Login → Navigate → Click → Remember what changed" with "ask in English" is equally obvious, **if you keep security boundaries**.

This agent is built on the principle: **Replace UI complexity, not human judgment.**

---

## Next Steps

- [x] Security framework (autonomy levels, host protection, audit logging)
- [x] Multi-source RAG (docs + forums + CVE + Reddit)
- [x] Transparent decision-making (reasoning chains, source attribution)
- [ ] Community feedback (your thoughts?)
- [ ] Helper script packaging (easy one-click install on Proxmox)
- [ ] MCP server wrapper (use from Cursor IDE, other Claude apps)

**Interested?** Try it on a test node. The worst that happens is a snapshot rollback.

---

## Links

- **Docs:** [SECURITY_LEVELS.md](github-link) — How autonomy, PVE protection, and pre-change backups work together
- **Trust Architecture:** [TRUST_ARCHITECTURE.md](github-link) — Addressing skeptics with evidence
- **RAG Sources:** [KNOWLEDGE_SOURCES.md](github-link) — Full breakdown of which sources are consulted and why
- **Code:** [GitHub repo](github-link) — MIT licensed, self-hosted on BananaPi or standalone LXC

---

**TLDR:** Built an AI agent for Proxmox that works like CAD/PDM (replaces clicks with conversation) but with security by design (you approve every change, full audit trail, multi-source verification, host protection). Not autonomous—decision-support. Ready for your feedback.
