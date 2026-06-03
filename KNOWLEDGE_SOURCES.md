# Knowledge Sources: Why This Agent Isn't "Just Reddit"

## The Criticism

From r/Proxmox thread on AI agents:
> "I wouldn't trust AI to manage my infrastructure. It will hallucinate. And when it breaks, nobody will help because it's an AI."

## Our Response

This agent consults **5 tiers of authoritative Proxmox knowledge**, ranked by reliability. Reddit is **Tier 4 of 5** (lowest priority). Here's why you can trust the sources:

---

## Tier 1: Official Proxmox Documentation (Weight: 3.0x)

**Authority:** Highest  
**Freshness:** Updated with each Proxmox release  
**Moderation:** Proxmox developers themselves

| Source | URL | What It Covers |
|--------|-----|---|
| PVE Admin Guide | https://pve.proxmox.com/pve-docs/pve-admin-guide.html | Complete reference: qm, pct, pvesm, firewall, clustering |
| PVE Wiki | https://pve.proxmox.com/wiki/ | Getting Help, Troubleshooting, Configuration |
| Release Notes | https://www.proxmox.com/en/proxmox-ve/ | Version-specific changes, breaking changes |
| API Documentation | https://pve.proxmox.com/pve-docs/api-viewer/ | REST API reference, tokens, authentication |
| Backup Server Docs | https://pbs.proxmox.com/pbs-docs/ | PBS client, restore procedures, deduplication |

**How agent uses Tier 1:**
- Ground truth for command syntax, config options, supported versions
- First source consulted before making recommendations
- Example: "qm set <vmid> --memory 4096" ← exact syntax from docs

**Example citation:**
```
Agent: "Docs recommend configuring ZFS ARC limit to 25% RAM"
[Link] https://pve.proxmox.com/pve-docs/chapter-storage.html#_zfs_specific_tuning
```

---

## Tier 2: Proxmox Community Forums (Weight: 2.0x)

**Authority:** High (moderated by Proxmox staff)  
**Freshness:** Real-time discussions, new issues within hours  
**Moderation:** Proxmox support team + community

| Source | URL | What It Covers |
|--------|-----|---|
| Proxmox Support Forum | https://forum.proxmox.com/ | 180k+ posts covering edge cases, failures, workarounds |
| Proxmox Mailing List | https://pve.proxmox.com/pve-docs/chapter-pve-intro.html | Developer discussions, pre-release announcements |
| Forum Categories | https://forum.proxmox.com/forums/ | Clustered, Storage, Networking, Backup, Virtualization |

**How agent uses Tier 2:**
- Real-world scenarios: "Users with ZFS on Ryzen hit this exact issue"
- Failure patterns: "3 reported Ceph OSD failures after upgrading to 8.2.1"
- Workarounds: "Solution: drain OSD before patching"
- Thread upvotes used to rank reliability

**Example citation:**
```
Agent: "45 users report successful pihole LXC creation"
[Link] https://forum.proxmox.com/threads/pihole-lxc-guide.12345/
       [45 upvotes] [82 replies] [Last reply: 3 days ago]
```

---

## Tier 3: Community Curations (Weight: 1.5x)

**Authority:** Moderate (well-maintained collections)  
**Freshness:** Updated weekly by community maintainers  
**Moderation:** GitHub stars, maintenance activity

| Source | URL | What It Covers |
|--------|-----|---|
| Awesome Proxmox VE | https://github.com/Corsinvest/awesome-proxmox-ve | Curated list of tools, scripts, resources |
| Community Helper Scripts | https://community-scripts.org/ | 150+ one-liner installers (Home Assistant, Docker, etc.) |
| Proxmox Blog | https://www.proxmox.com/en/blog | Case studies, new features, best practices |

**How agent uses Tier 3:**
- Discovers helper scripts for common workloads
- Links to maintained tools + community reviews
- Alerts on best practices from official blog

**Example citation:**
```
Agent: "Popular helper script for Home Assistant (1.2k GitHub stars, maintained)"
[Install] https://community-scripts.org/ct-homeassistant.html
          bash -c "$(curl -fsSL https://...)"
```

---

## Tier 4: Reddit (Weight: 0.8x)

**Authority:** Low (unmoderated, signal/noise ratio)  
**Freshness:** Real-time but includes outdated advice  
**Moderation:** Community upvotes (imperfect)

| Source | URL | What It Covers |
|--------|-----|---|
| r/Proxmox | https://www.reddit.com/r/Proxmox/ | 25k members, community discussion, gotchas |

**How agent uses Tier 4:**
- Community trends: "What are people talking about this week?"
- Sentiment: "User feedback on new features"
- **NOT** for critical advice (too much misinformation)
- Only shows posts with 50+ upvotes and <30 days old

**Example citation:**
```
Agent: "Reddit users report: ZFS+ARM64 issues this week"
[Post] https://reddit.com/r/Proxmox/comments/...
       [87 upvotes] [32 comments] [Posted 5 days ago]
       
⚠️ Not official guidance—community discussion only.
   Check official docs for definitive answer.
```

---

## Tier 5: CVE Databases (Real-Time Critical Override)

**Authority:** Highest (national security data)  
**Freshness:** Real-time, updated hourly  
**Moderation:** NIST, Debian, Ubuntu security teams

| Source | URL | What It Covers |
|--------|-----|---|
| NIST NVD | https://nvd.nist.gov/vuln/search | All public CVEs, CVSS scores |
| Debian Security Tracker | https://security.debian.org/ | Debian package advisories |
| Ubuntu Security | https://ubuntu.com/security/notices | Ubuntu LTS patch availability |

**How agent uses Tier 5:**
- **Blocks** operations if critical CVE is unfixed
- Recommends patches based on severity
- Real-time: "New CVE found in OpenSSL — patch now"
- Overrides all other tiers (security > stability)

**Example citation:**
```
Agent: "⚠️ CRITICAL: CVE-2024-12345 in libc-bin
       CVSS Score: 9.8 (Network exploitable)
       Patch available: libc-bin 2.36-10
       [Patch now] [Defer]"
```

---

## How Search Works (Hybrid Ranking)

Agent uses **BM25 keyword matching** across all tiers with authority weighting:

```
relevance_score = (keyword_match) × (tier_weight) × (freshness_bonus)

Example: "How do I configure ZFS ARC?"

Results ranked:
  1. Official docs mention "ARC" with config syntax (Tier 1, weight 3.0x) → Ranked #1
  2. Forum thread "ZFS tuning for 1GB RAM" (Tier 2, weight 2.0x, 120 upvotes) → Ranked #2
  3. Helper script for ZFS optimization (Tier 3, weight 1.5x) → Ranked #3
  4. Reddit "just use defaults lol" (Tier 4, weight 0.8x, 12 upvotes) → Ranked #5
```

**Freshness bonus:**
- Updated in last 7 days: +20%
- Last 30 days: +10%
- Last 90 days: +5%
- Older: -10%

---

## Transparency: [View Sources] Button

Every recommendation card includes `[View all sources]` to show full search:

```
┌──────────────────────────────────────────────────┐
│ Recommendation: Patch pihole                     │
│                                                  │
│ Sources consulted (ranked by authority):        │
│                                                  │
│ 🏆 TIER 1 (Official Docs) — weight 3.0x         │
│    ✓ https://pve.proxmox.com/pve-docs/...       │
│    "Apply updates monthly for security"         │
│                                                  │
│ 👥 TIER 2 (Forum) — weight 2.0x                 │
│    ✓ 12 discussions, 0 recent failures          │
│    https://forum.proxmox.com/threads/...        │
│                                                  │
│ ⚠️  TIER 5 (CVE Database)                        │
│    ✓ 1 medium-severity CVE found + fixed        │
│    https://nvd.nist.gov/vuln/detail/...         │
│                                                  │
│ ~ TIER 4 (Reddit) — weight 0.8x                 │
│    ⚠️ "working fine" (weak signal, not priority)│
│    https://reddit.com/r/Proxmox/...             │
│                                                  │
│ CONSENSUS: 3 authoritative tiers agree → Patch  │
└──────────────────────────────────────────────────┘
```

---

## Trust Building: Conflicts Are Transparent

When sources disagree, agent shows all perspectives:

### Example: ZFS vs ext4

```
Tier 1 (Docs): "ext4 is simpler, ZFS is more powerful"
Tier 2 (Forum): "ZFS if you have 8GB+ RAM, ext4 for minimal setups"
Tier 4 (Reddit): "ext4 is more stable" (anecdotal)

Agent output:
  Official docs recommend: "Choose based on workload"
  
  Forum consensus: ZFS requires spare RAM (1GB per TB storage)
  
  Analysis: All tiers agree on the tradeoff.
           Your system has 16GB RAM → ZFS is viable
  
  Recommendation: Your choice. ZFS for better features, ext4 for simplicity
  
  [Choose ZFS] [Choose ext4]
```

---

## Why This Matters to You

### Addressing the "Reddit Skeptics"

**Skeptic says:** "AI agents just search Reddit and give bad advice"

**You respond:** "Mine consults official Proxmox docs first. Reddit is Tier 4 of 5 sources. Every recommendation shows its sources. You can click and verify."

### Addressing the "Nobody Will Help" Concern

**When something goes wrong:**
1. Full audit trail shows what was recommended + sources consulted
2. Reasoning chain explains why agent thought it was safe
3. Community sees the decision → can help you debug
4. Snapshots/rollback available for most operations

**Community can see:**
```
"Here's what the agent recommended: [sources]
 Here's what I approved: [approval log]
 Here's what went wrong: [failure log]
 What should I do?"
```

vs. Random script that breaks things (no audit trail, no help available)

---

## Refresh Schedule

| Tier | Refresh | Method |
|------|---------|--------|
| **Tier 1** (Official) | Daily | Scrape PVE docs site |
| **Tier 2** (Forums) | Weekly | Forum RSS + Proxmox API |
| **Tier 3** (Scripts) | Weekly | GitHub RSS polling |
| **Tier 4** (Reddit) | On-demand | Reddit API (rate-limited) |
| **Tier 5** (CVE) | Real-time | NIST NVD API v2 |

---

## Real-World Example: "Should I upgrade to Proxmox 8.2?"

Agent searches all 5 tiers and reports:

```
✓ TIER 1 (Official Docs)
  Upgrade guide: https://pve.proxmox.com/pve-docs/chapter-upgrade.html
  "Upgrade path: 7.4 → 8.0 → 8.2 is recommended"

✓ TIER 2 (Forum)
  Recent upgrade experiences: 23 threads in last month
  - 21 successful upgrades (0 major issues)
  - 2 reported glitches (fixed in 8.2-1)
  https://forum.proxmox.com/threads/8-2-upgrade-guide.54321/

✓ TIER 5 (CVE)
  New CVE in 8.1.x: CVE-2024-12345 (high)
  Status: Fixed in 8.2-1
  https://nvd.nist.gov/vuln/detail/CVE-2024-12345

~ TIER 4 (Reddit)
  "8.2 is stable" (weak signal, 34 upvotes)
  "Anyone else hit IOMMU bug?" (3 upvotes)
  https://reddit.com/r/Proxmox/...

CONSENSUS:
  • Official path supports 8.2
  • 21+ users upgraded successfully
  • 1 critical CVE is fixed in 8.2
  • Pre-flight: PBS backup before upgrade
  
RECOMMENDATION: Safe to upgrade
CONFIDENCE: 95%

[Upgrade now] [Ask community more questions] [Defer]
```

User reads this, clicks the forum link (23 threads!), feels confident, upgrades.

---

## Summary

Your agent is **not "just Reddit"**. It consults:

1. **Official Proxmox documentation** (ground truth)
2. **Community forums moderated by Proxmox staff** (peer-verified edge cases)
3. **Well-maintained community scripts** (curated tools)
4. **Real-time CVE databases** (critical security threats)
5. **Reddit** (community trends, lowest priority)

Every recommendation shows its sources. You can verify everything. Conflicts are transparent. You control the approval.

**That's why you can defend this to skeptics:** "It's not a black box. It shows its work. If something goes wrong, I have a full audit trail and community can help because they see what happened."

Sources:
- [Proxmox Official Documentation](https://pve.proxmox.com/pve-docs/)
- [Proxmox Community Forum](https://forum.proxmox.com/)
- [Community Scripts](https://community-scripts.org/)
- [NIST CVE Database](https://nvd.nist.gov/vuln/search)
- [r/Proxmox](https://www.reddit.com/r/Proxmox/)
