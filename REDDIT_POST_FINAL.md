# r/Proxmox: I built an AI agent inspired by how CAD/PDM replaced GUIs—but with security by design

I come from an engineering background (CAD, PDM systems), where I've seen AI replace 10-click workflows with conversation. But infrastructure is different—one wrong click can break your homelab. So I built a **Proxmox agent that replaces GUI complexity with AI, but you stay in control**.

## The Problem

Proxmox GUI requires:
- Click Datacenter → Permissions → API Tokens → Add
- Navigate Storage → Content → Upload ISO
- Search logs across 5 VMs
- Trial-and-error snapshots
- Manual patch sequencing

**What if you could just ask:** *"Are my backups healthy? Patch pihole if safe. Run a security audit."*

I expected Reddit to say: *"AI will hallucinate and break my host."* Fair point. So this isn't autonomous—it's **decision-support with hard security boundaries**.

## How It's Different: Security by Design

### 1. You Approve Every Write
```
Default mode: "Suggest" (Level 1)
Agent proposes → Shows dry-run → You click [Run]
Nothing happens without your explicit approval
```

Not "autonomous agent that learns from mistakes"—you see the reasoning before it runs.

### 2. Multi-Source Verification (Not Reddit Alone)
The agent searches 5 tiers of sources, ranked by reliability:

- **Tier 1:** Official Proxmox docs (pve.proxmox.com) — ground truth
- **Tier 2:** Proxmox forums (moderated by Proxmox staff) — peer-verified
- **Tier 3:** Community scripts + curations
- **Tier 4:** Reddit discussions — lowest priority, trends only
- **Tier 5:** Real-time CVE database (NIST NVD) — critical override

Every recommendation shows which sources were consulted. You can click and verify.

### 3. Host Protection (Can't Accidentally Break PVE)
Three modes:
- **Strict (default):** Proxmox host writes blocked entirely
- **Warn:** Allowed but requires pre-flight PBS backup first
- **Off:** Only for dev/test nodes

### 4. Full Audit Trail
Every operation logged:
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
  "reasoning": ["Official docs recommend monthly patching", "Forum: no recent failures"],
  "action": "executed",
  "result": "12 packages updated",
  "reversible": true,
  "rollback_available": "snapshot-pihole-20260603-143200"
}
```

Export anytime. Share with community if something breaks—they see the full decision chain.

### 5. Autonomy Levels (Progressive Trust)
- **Level 0 (Observe):** Read-only. Agent can only query.
- **Level 1 (Suggest):** Draft → you approve each action [default]
- **Level 2 (Maintain):** Auto-patch guests (not host). Pre-flight snapshots.
- **Level 3 (Full):** Autonomous (dev/test only, high risk)

Start at Level 1. Graduate to Level 2 after you've verified judgment.

## What This Enables

**Example Flow:**
```
User: "patch pihole and check backups"

Agent:
  ✓ Consulting official Proxmox docs...
  ✓ Searching forum for pihole patch issues...
  ✓ Checking CVE database...
  
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

## Addressing the Skeptics

**"AI will hallucinate."**
- Consults 5 tiers of sources (docs > forums > scripts > Reddit > CVE)
- Shows reasoning chain
- You approve before it runs
- Audit trail if something breaks

**"When it breaks, nobody will help me."**
- Full decision log shows what sources were consulted
- Reasoning explains why the agent thought it was safe
- Community can debug from audit trail
- Snapshot rollback available

**"I don't trust AI agents."**
- Not autonomous—it's a decision-support tool
- Default mode requires your approval for every action
- Host protection prevents accidental PVE breakage
- Like CAD PDM: replaces clicks, not responsibility

## The Tech

- **Architecture:** FastAPI + vanilla JS + SSE streaming (real-time UI)
- **RAG:** BM25 keyword search over official docs + environment state + CVE database
- **LLM:** Claude with extended thinking for patch safety assessment
- **Tools:** 26 integrated (inventory, patch, backup, networking, snapshots, CVE lookup, Reddit search, etc.)
- **Storage:** JSONL audit logs, snapshots for rollback, PBS for incremental backups
- **Deployment:** Lightweight LXC (150MB) or Pi/BananaPi, or standalone on Proxmox host

## Open Source

**GitHub:** https://github.com/config-collab/proxmox-agent

- MIT licensed
- Full documentation (architecture, security framework, guides)
- 87 files, ~15k LOC
- No secrets committed (API keys blocked, .env is template only)

## Security Checklist

- [x] Conservative defaults (read-only by default)
- [x] Multi-source verification (official > forums > Reddit)
- [x] Pre-flight backups (snapshots + PBS)
- [x] Host protection (can't touch PVE without explicit permission)
- [x] Approval workflow (nothing runs without you clicking)
- [x] Full audit trail (every decision logged + exportable)
- [x] Rollback available (snapshots + PBS restore)
- [x] Community-verifiable (reasoning shown, sources cited)

## TL;DR

Built an AI agent for Proxmox that works like how AI replaced complex GUIs in CAD/PDM—replaces clicks with conversation. But with security by design: you approve every change, full audit trail, multi-source verification (official docs checked first—Reddit is last), host protection prevents accidental PVE breakage.

**Not autonomous. Decision-support. You're in control.**

Try it on a test node. Worst case: snapshot rollback.

---

**Repo:** https://github.com/config-collab/proxmox-agent

**Docs:** README.md covers architecture, deployment, 26 tools, security framework, troubleshooting.

Feedback welcome. What would you want in a Proxmox assistant?
