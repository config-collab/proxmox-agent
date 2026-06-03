# Trust Architecture: Addressing Skeptics

This document outlines how the agent builds credibility against the "I wouldn't trust AI with my infrastructure" critique.

## The Reddit Criticism

> "I wouldn't trust AI agents to manage infrastructure. They hallucinate, they can break things, and when they do, I'm alone."
> 
> "The issue is: nobody will help you when (not if!) your host breaks because of AI suggestions."

**Our response:** Not autonomy, not black-box reasoning, but radical transparency + conservative defaults + community consensus + real-time verification.

---

## 5 Pillars of Trust

### 1. Conservative Defaults (Level 1 = Suggest Only)

| Setting | Default | Can User Change? | Lock? |
|---------|---------|------------------|-------|
| **Autonomy Level** | 1 (Suggest) | Yes | No |
| **PVE Protection** | Strict | Yes | No |
| **Pre-change Backup** | Snapshot | Yes | No |
| **Host Write Access** | Blocked | Yes (warn/off modes) | No |

**Philosophy:** Agent is opt-in for autonomous actions. You must click "Run" or "Apply" for every write. If the agent breaks something, you caught it before it happened because you had to approve it.

**Example:**
```
User: "patch everything"
Agent: [Can't—autonomy level is 1]
       "Dry-run for pihole:
         apt update && apt upgrade
        
        These r/Proxmox threads discuss pihole patches:
        [Thread 1: 45 upvotes, 'works great']
        [Thread 2: 8 upvotes, 'watch for service restart']
        
        Official docs recommend: Apply updates monthly
        
        Pre-flight: Taking VM snapshot first
        
        Ready to run? [Yes] [Show reasoning] [Ask community first]"

User clicks [Yes]
→ Snapshot created
→ Patches applied
→ Rollback available for 24h
```

---

### 2. Multi-Source Verification (Not Reddit Alone)

**5-Tier Authority Ranking:**

```
Tier 1: Official Proxmox Docs (pve.proxmox.com)
        ↓ [ALWAYS checked first, most authoritative]
        
Tier 2: Proxmox Community Forums (forum.proxmox.com)
        ↓ [Moderated by Proxmox team, peer-verified]
        
Tier 3: Community Curations (community-scripts.org, GitHub)
        ↓ [Well-maintained collections by community]
        
Tier 4: Reddit (r/Proxmox)
        ↓ [Community sentiment, trends, gotchas]
        
Tier 5: Real-time CVE Database (NIST NVD)
        ↓ [Critical override—blocks unsafe operations]
```

**How agent uses them:**
- Tier 1 is ground truth for command syntax, configuration, best practices
- Tier 2 is ground truth for "what went wrong for others" and edge cases
- Tier 3 surfaces curated tools and installation recipes
- Tier 4 is "what are people talking about this week" (lowest priority)
- Tier 5 blocks patches if critical CVE is unfixed

**Example: User asks "Should I patch the Proxmox host?"**

Agent searches all 5 tiers:

```
✓ TIER 1 (Official): "pveversion docs recommend patching monthly for security"
  → https://pve.proxmox.com/pve-docs/chapter-pve-intro.html

✓ TIER 2 (Forum): 12 recent discussions, 0 reported failures with latest patch
  → https://forum.proxmox.com/threads/pve-8-2-patch.54321

✓ TIER 5 (CVE): NIST NVD check — 1 high-severity CVE in current version
  → https://nvd.nist.gov/vuln/detail/CVE-2024-12345

~ TIER 4 (Reddit): 8 upvotes, mostly positive, "easy update"
  → https://reddit.com/r/Proxmox/...

→ CONSENSUS: Official docs recommend, forum shows no failures, CVE is critical
→ CONFIDENCE: HIGH (3 authoritative tiers agree)
→ RECOMMENDATION: Yes, patch now
```

**Conflicts are shown transparently:**
```
Tier 1 says: "Use ext4 for performance"
Tier 2 says: "ZFS is better if you have spare RAM"
Tier 4 says: "ext4 is more stable"

→ Agent shows all three, explains the context (ZFS needs 1GB RAM per TB storage), 
  lets user decide.
```

---

### 3. Full Audit Trail (Exportable & Verifiable)

Every operation logged in JSONL format:

```json
{
  "timestamp": "2026-06-03T14:32:15Z",
  "operation": "apply_patches",
  "target": "pihole-lxc",
  "autonomy_level": 1,
  "pre_flight_action": "snapshot_created",
  "sources_consulted": [
    "pve.proxmox.com:pve-docs/chapter-patching.html",
    "forum.proxmox.com/threads/pihole-patches-12345",
    "nvd.nist.gov/vuln/detail/CVE-2024-...",
    "reddit.com/r/Proxmox/..."
  ],
  "reasoning_chain": [
    "Official docs recommend monthly patching",
    "Forum consensus: no recent pihole update failures",
    "CVE check: 0 critical, 1 medium severity in current version",
    "Pre-flight: VM snapshot taken before patch"
  ],
  "action": "executed",
  "result": "12 packages updated, 0 failures",
  "reversible": true,
  "rollback_available": "snapshot-pihole-20260603-143200"
}
```

**User can:**
- Export full audit log → JSON / CSV / Markdown
- Search by date, operation, target
- Compare "what agent did" vs "what actually happened"
- Share with community if something breaks (transparent blame assignment)

**URL:** `/api/audit` → download full history

---

### 4. Reasoning Transparency (Why, Not Just What)

Every recommendation includes chain-of-thought:

```
[Recommendation card in UI]

┌──────────────────────────────────────┐
│ Patch pihole                         │
├──────────────────────────────────────┤
│ Reasoning:                           │
│                                      │
│ 1. CVE check (NIST)                 │
│    → Found 1 medium-severity CVE in │
│      libc-bin 2.36-9                │
│    → Upgrade to 2.36-10 available   │
│                                      │
│ 2. Official guidance                │
│    → Docs recommend patching >30d   │
│    → Last patch: 45 days ago        │
│                                      │
│ 3. Community check                  │
│    → Forum: 0 recent failures       │
│    → Reddit: "working fine" (weak)  │
│                                      │
│ 4. Pre-flight protection            │
│    → Will snapshot pihole-lxc first │
│    → Rollback available for 24h     │
│                                      │
│ 5. Autonomy check                   │
│    → You're at Level 1 (Suggest)    │
│    → You must approve each action   │
│                                      │
│ DECISION: Safe to patch             │
│ CONFIDENCE: 95% (3/4 sources agree) │
│                                      │
│ [Run] [Ask community first] [Defer] │
└──────────────────────────────────────┘
```

Click `[Show reasoning]` to see full chain above.

---

### 5. Community Consensus Check (Not Solo Decision)

Before risky operations, agent searches community for:
- Have others done this?
- Did it work?
- What went wrong?

**Example:**
```
User: "Upgrade Ceph cluster to Reef"

Agent automatically searches:
  1. Official docs → upgrade procedures
  2. Forum → "ceph reef upgrade" → 23 threads, no recent failures
  3. Reddit → trends this month (5 discussions, mostly positive)
  4. CVE DB → Reef known vulnerabilities (7 medium, 1 high from 2025)
  
Consensus Summary:
  ✓ Officially supported
  ✓ Community has done it successfully (23 forum threads, 0 critical issues)
  ✓ Recommendation: patch 1 high-severity CVE first
  
Pre-flight:
  1. PBS incremental backup of Ceph config
  2. Drain 1 OSD (smallest)
  3. Upgrade it
  4. Watch for 24h
  5. Then upgrade remaining
  
[Run test upgrade on 1 OSD] [Run full cluster upgrade] [Skip for now]
```

---

## Trust Mechanics in Practice

### Scenario 1: User Sees Failure Coming (Success!)

```
User: "patch production pihole"
Agent: [takes snapshot]
       "Pre-flight snapshot: pihole-20260603-14:32:00
        
       Dry-run shows 47 packages would change.
       
       Searching for known issues..."
       
       [10 seconds]
       
       "⚠️  Found: 1 Reddit thread from last week, user reported
           pihole 5.18 broke DNS on ARM64.
           
           Your system: NOT ARM64 (you're x86-64)
           
           Recommendation: Safe to patch, ARM64 issue doesn't affect you.
           
       [Run] [Ask community why ARM64 broke] [Defer]"

User clicks [Ask community why ARM64 broke]

Agent searches forum for "pihole ARM64 DNS" → finds root cause + workaround

User is informed, can choose: patch anyway, or wait for 5.18.1
```

**Result:** User trusts agent because it found a real issue, explained why it doesn't apply, and gave them the choice.

---

### Scenario 2: User Spots Conflict (Transparency!)

```
Agent: "Patch Proxmox host
        
        Official docs: ✓ Recommend patching monthly
        Forum (12 threads): ✓ No recent failures
        CVE (NIST): 1 critical security fix
        Reddit: 'wait for .1 release' (8 upvotes)
        
        ⚠️  CONFLICT: Tier 4 (Reddit) suggests waiting, 
                      Tier 1-2 recommend patching now.
        
        Analysis: Official docs are more reliable than Reddit anecdotes.
                 CVE is critical (security > stability in this case).
        
        Recommendation: Patch now
        But: You decide. [View all sources] [Skip] [Run]"

User clicks [View all sources] → See all 5 tiers + full thread links

User reads Reddit thread → sees it's about a non-security regression

User decides: Security > stability, patches now
```

**Result:** User made the decision, informed by real sources, not a black box.

---

## Marketing Claims (Evidence-Based)

✗ "Our AI agent intelligently manages your infrastructure"
✓ "Decision-support tool backed by official Proxmox docs, community forums, and real-time CVE data. You approve every action."

✗ "Fire and forget automation"
✓ "Suggest → Pre-flight verify → Snapshot → Execute → Audit trail → Rollback available"

✗ "Never breaks anything"
✓ "Defaults to read-only. Snapshots before changes. Full audit log so you can see exactly what happened and roll back."

---

## Addressing the Reddit Skeptics Directly

**Skeptic:** "AI will hallucinate and destroy my infrastructure."
**Response:** "Default mode is 'Suggest'—you see the dry-run and approve before anything happens. If it hallucinates, you catch it at the dry-run stage. You're in control."

**Skeptic:** "It will search Reddit and give bad advice."
**Response:** "Reddit is Tier 4 of 5 sources. Official Proxmox docs are Tier 1. Forums moderated by Proxmox team are Tier 2. Real-time CVE checks are critical override. Every recommendation shows its sources—you can verify."

**Skeptic:** "When it breaks my host, nobody will help me."
**Response:** "Full audit trail shows exactly what happened. You can share that with the community, and they'll be able to help because they see the full decision chain. Plus, snapshots + rollback window means you can undo most changes."

**Skeptic:** "It's still just an AI making decisions."
**Response:** "It's a decision-support tool. The AI makes recommendations, you approve them. The AI shows its reasoning. The AI logs everything. You can audit, compare, and decide."

---

## Trust KPIs

Track these to prove trustworthiness:

1. **Approval Rate**: % of recommendations user approves
   - Target: 90%+ (means agent's suggestions are usually right)
   
2. **Rollback Rate**: % of operations that got rolled back
   - Target: <2% (means very few mistakes)
   
3. **Audit Trail Completeness**: % of operations with full reasoning
   - Target: 100% (means no black-box operations)
   
4. **Source Diversity**: Average # of tiers consulted per recommendation
   - Target: 3-5 (means thorough research)

5. **Community Verification**: % of recommendations cross-checked with forums/CVE
   - Target: 100% for risky ops (patch, network, storage changes)

---

## What Happens When Agent Makes a Mistake

**Scenario:** Agent recommends a patch that breaks the service.

**What you'll see:**
1. Pre-flight snapshot was taken (reversible)
2. Audit log shows all sources consulted + reasoning
3. Service failure detected automatically (health check)
4. Rollback button appears: "Restore from snapshot-xyz"
5. User exports audit → shares with r/Proxmox
6. Community sees: "Here's the decision chain. Agent consulted docs + forum + CVE. Here's what went wrong."
7. Agent learns: "This combination of packages breaks service X on hardware Y"
8. Future recommendations are updated with this knowledge

**vs. Random script that breaks your host:**
- No reasoning chain
- No audit trail
- No rollback
- No way to tell community what happened
- Random internet stranger who wrote it is unreachable

---

## Bottom Line

This agent is trustworthy because:

1. **Conservative by default** — Suggest mode, approval required, snapshots enabled
2. **Multi-source verified** — Consults official docs first, forums second, Reddit last
3. **Fully auditable** — Every decision logged and exportable
4. **Transparent reasoning** — Shows its thinking, not a black box
5. **Community consensus** — Checks what others have done before recommending
6. **Reversible operations** — Snapshots + rollback for most changes

**You can explain your trust to skeptics:** "It's not autonomous. It's a tool that shows its work. If something goes wrong, I have a full audit trail and can roll back. The AI consults official docs, forums, and CVE databases—not Reddit alone."
