# RAG Knowledge Sources for Proxmox Agent

This document maps all knowledge sources the agent consults before making recommendations. This addresses trust concerns by showing the agent's reasoning is grounded in official, community-vetted, and enterprise resources—not just speculation or Reddit.

## Tier 1: Official Proxmox Resources (Highest Authority)

**Weight: 3.0x in keyword search**

| Source | URL | Type | Refresh |
|--------|-----|------|---------|
| PVE Admin Guide | https://pve.proxmox.com/pve-docs/pve-admin-guide.html | Official docs | Daily |
| PVE Wiki | https://pve.proxmox.com/wiki/ | Official reference | Daily |
| Proxmox Documentation | https://www.proxmox.com/en/downloads/proxmox-virtual-environment/documentation | Release docs | Per release |
| Proxmox Bugzilla | https://bugzilla.proxmox.com | Issue tracking | Real-time |
| Release Notes | https://pve.proxmox.com/pve-docs/chapter-pve-intro.html | Version notes | Per release |

**How agent uses Tier 1:**
- Primary source for "best practice" claims
- Definitive on API behavior, configuration syntax, supported versions
- Cites official docs when recommending major changes
- Flags if documentation conflicts with advice

---

## Tier 2: Proxmox Community Forums (Peer-Verified)

**Weight: 2.0x in keyword search**

| Source | URL | Type | Moderation |
|--------|-----|------|-----------|
| Proxmox Support Forum | https://forum.proxmox.com/ | Q&A, peer support | Staff + community |
| Proxmox Mailing Lists | https://pve.proxmox.com/pve-docs/chapter-pve-intro.html#getting-help | Technical discussion | Developer oversight |
| Proxmox Getting Help | https://pve.proxmox.com/wiki/Getting_Help | Support guide | Official |

**How agent uses Tier 2:**
- Shows real-world scenarios (e.g., "User on forum had ZFS pool failure with these symptoms...")
- Validates rare edge cases not covered in docs
- Pulls actual solutions that worked for similar hardware/versions
- Attributes credit to forum threads + upvote counts
- Cites thread URLs so user can read full context

---

## Tier 3: Community Curations (Well-Maintained Collections)

**Weight: 1.5x in keyword search**

| Source | URL | Type | Maintained |
|--------|-----|------|-----------|
| Awesome Proxmox VE | https://github.com/Corsinvest/awesome-proxmox-ve | Curated list | Community |
| Proxmox Helper Scripts | https://community-scripts.org/ | Installation scripts | Community |
| Proxmox Blog | https://www.proxmox.com/en/blog | Case studies, announcements | Official |

**How agent uses Tier 3:**
- Discovers helper scripts for common workloads (Docker, Kubernetes, Vaultwarden, etc.)
- Alerts on new best practices from Proxmox blogs
- Links to community tools for extended functionality
- Notes maintenance status (active vs. abandoned)

---

## Tier 4: Reddit (Low Priority, For Context Only)

**Weight: 0.8x in keyword search**

| Source | URL | Type | Moderation |
|--------|-----|------|-----------|
| r/Proxmox | https://www.reddit.com/r/Proxmox/ | Community discussion | Community |

**How agent uses Tier 4:**
- Only for common gotchas, user sentiment, and recent trends
- Never sole source for critical advice
- Shows posts with upvotes > 50 and recent comments only
- Clearly labels as "community discussion, not official guidance"
- Compares Reddit claims against Tier 1-2 sources before endorsing

---

## Tier 5: CVE & Security Databases (Real-Time Threats)

**Weight: Critical severity override**

| Source | URL | Type | Real-time |
|--------|-----|------|-----------|
| NIST NVD v2 | https://nvd.nist.gov/vuln/search | CVE tracking | Real-time |
| Debian Security Tracker | https://security.debian.org/ | Package CVEs | Real-time |
| Ubuntu Security | https://ubuntu.com/security/notices | Package CVEs | Real-time |
| Proxmox Security Advisories | https://www.proxmox.com/en/services/security-advisories | Official advisories | Real-time |

**How agent uses Tier 5:**
- Alerts on high-severity CVEs in installed packages
- Cross-references version numbers against NVD
- Recommends patches based on CVSS score
- Links to official patch availability per distro
- Blocks risky operations if unpatched critical CVE is present

---

## How Search Works (Hybrid Ranking)

Agent uses **BM25 keyword search** across all tiers with authority weighting:

```
relevance_score = (BM25_base) × (tier_weight) × (freshness_bonus)

Example: "How do I configure ZFS ARC?"
1. PVE docs mention ARC (weight 3.0) → ranked #1
2. Forum thread with 120 upvotes (weight 2.0) → ranked #2  
3. Reddit post saying "just use defaults" (weight 0.8) → ranked #5
4. Helper script for ZFS tuning (weight 1.5) → ranked #3
```

**Freshness bonus:**
- Docs updated in last 7 days: +20%
- Forum posts from last 30 days: +10%
- Reddit posts from last 90 days: +5%
- Archived/old posts: -10%

---

## Citation Format in Agent Responses

Every recommendation includes source tier:

### ✓ High Confidence
```
[Official Docs] "Use ext4 for VPS guests" 
  → https://pve.proxmox.com/pve-docs/chapter-storage.html
```

### ✓ Community Consensus
```
[Forum] 45+ users report success with Ceph on 3-node clusters
  → https://forum.proxmox.com/threads/ceph-guide.12345
```

### ⚠️ Rare Edge Case
```
[Forum] One user hit this exact error on Ryzen 7950X + ZFS
  → https://forum.proxmox.com/threads/zfs-ryzen.54321
```

### ⚠️ Conflicting Sources
```
[Conflict] Official docs say X, but forum users report Y on ARM64
  → Show both, let user decide
```

### ⛔ No Credible Source
```
❌ "I found on Reddit that disabling SELinux improves performance"
   No official docs support this. Recommend testing in dev first.
```

---

## RAG Refresh Schedule

| Tier | Refresh | Method | Cache |
|------|---------|--------|-------|
| Tier 1 (Official) | Daily | Scrape PVE docs | 24h |
| Tier 2 (Forums) | Weekly | Forum RSS + API | 7d |
| Tier 3 (Curations) | Weekly | GitHub RSS | 7d |
| Tier 4 (Reddit) | On-demand | Reddit API | 1h |
| Tier 5 (CVE) | Real-time | NVD API v2 | 30min |

---

## Preventing the "AI Hallucination" Critique

### Agent Rules

1. **Never cite a source that wasn't actually consulted**
   - Return `"[Source not found]"` if RAG didn't match anything
   - Don't invent forum threads or "common knowledge"

2. **Always compare tiers before recommending**
   - If Tier 1 and Tier 4 conflict, show both + recommend Tier 1
   - Example: "Docs say A, but some users report B. Here's the difference..."

3. **Flag unverified claims**
   - "Some Reddit users claim X, but I found no official confirmation"
   - "No documentation for this edge case. Community workaround: [thread]"

4. **Require user confirmation for risky ops**
   - Even if all tiers agree, show reasoning chain
   - Example: "Tier 1 + 5 forum threads + NVD all say: patch now"

5. **Publish audit trail**
   - User can export: which sources were consulted, weights applied, conflicts noted
   - Builds trust: "Here's exactly what I looked at"

---

## Integration with Agent Tools

### `search_docs(query)` 
- Searches Tier 1 only
- Returns exact doc URLs + context
- Example: "What does vm memory balloon do?"

### `search_forum(query)`
- Searches Tier 2 (Forums + mailing lists)
- Returns threads with author, upvote count, date
- Example: "Users encountering Ceph OSD failures"

### `search_cve(package, version)`
- Searches Tier 5 (NVD + distro trackers)
- Returns severity, CVSS score, patch availability
- Example: "Is OpenSSL 1.1.1w vulnerable to CVE-2024-1234?"

### `compare_with_community(operation, recommendation)`
- Searches Tiers 2-4 for similar operations
- Aggregates votes, warnings, alternative approaches
- Example: "Before patching, what do others say about this guest?"

### `ask_community(question)`
- Searches Tier 2-4 for existing answers
- Returns curated thread titles + upvote counts
- Falls back to: "No exact match, but similar discussions: [threads]"

### `trending_proxmox()`
- Aggregates Tier 2-4 activity (new posts, trending topics)
- Shows what community is talking about NOW
- Example: "Everyone's discussing ZFS on ARM64 this week"

---

## Example: "Should I patch now?" Flow

```
User: "patch pihole"

Agent searches:
  ✓ Tier 1: "pihole update security practices" → official docs URL
  ✓ Tier 2: "pihole patch failures" → forum threads (0 recent, 2 old)
  ✓ Tier 5: "pihole packages CVEs" → NVD query for versions
  ~ Tier 4: "pihole updates reddit" → 3 recent threads, 2 outdated

Agent output:
  [Official] Pihole docs recommend: "Apply security updates monthly"
    → https://docs.pi-hole.net/...
  
  [CVE Search] Found 0 critical CVEs in pihole 5.17.1
    → Recommended update: pihole 5.18
  
  [Forum] No recent issues reported with pihole updates
    → (Only 2 discussions, both >1 year old)
  
  [Community] Reddit trend: pihole compatibility with next Ubuntu LTS
    → 12 upvotes, but not related to your patch
  
  [Reasoning]
    • No critical CVEs blocks patching
    • Forum has no recent failure reports
    • Docs encourage regular updates
    • Taking snapshot first (pre-flight backup)
  
  Recommendation: ✓ Safe to patch
  
  [Audit Trail] 5 sources checked, 3 recommend patching, 0 advise against
```

---

## Trust Building in UI

Every agent recommendation card shows:

```
┌─────────────────────────────────┐
│ Recommendation: Patch pihole    │
│                                 │
│ Based on 5 sources:             │
│  ✓ Official docs               │
│  ✓ CVE database (0 critical)   │
│  ✓ 12 forum discussions        │
│  ~ Reddit consensus (weak)     │
│                                 │
│ [View sources] [Export audit]   │
│ [Run] [Show reasoning]          │
└─────────────────────────────────┘
```

Click `[View sources]` → full list with clickable links.

---

## Community Trust Lever

**Addressing skeptics:**
> "This agent is not a black box. It consults official Proxmox docs, forums moderated by the Proxmox team, and CVE databases in real-time. Every recommendation shows its sources. You can export the full audit trail and verify every claim."

**In marketing/docs:**
> "Powered by official Proxmox documentation, peer-reviewed community forums, and real-time CVE tracking. Never guesses."
