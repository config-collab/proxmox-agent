# Security Levels & Autonomy Model

This agent uses **two orthogonal security dimensions** that work together:

## 1. AUTONOMY LEVELS (Agent Autonomy — what can the LLM do without asking?)

Set via `AGENT_AUTONOMY` env var (0-3):

### Level 0: **Observe** ⊘ (Read-Only)
```
AGENT_AUTONOMY=0
```
- **What it can do:** Query, report, explain, search community/docs
- **What it CANNOT do:** Execute ANY write operations
- **Use case:** Homelab users who trust the reasoning but not any automatic actions
- **Approval:** No approvals needed — agent is fundamentally read-only
- **Risk:** Zero — worst case is a misleading report that you ignore

**Example flow:**
```
User: "patch my homelab"
Agent: "Here are patches. Dry-run would look like: [command]. 
        r/Proxmox says [upvoted threads]. 
        Do you want me to draft a change?"
User: "No, I'll do it manually."
Agent: [Cannot proceed, all write ops blocked]
```

---

### Level 1: **Suggest** ⋯ (Draft & Confirm)
```
AGENT_AUTONOMY=1  # Default
```
- **What it can do:** Propose actions, show dry-runs, require explicit confirmation clicks
- **What it CANNOT do:** Execute anything without human approval in the UI
- **Use case:** Most users — agent is helpful but you're in control
- **Approval:** Click "Run" button for each operation
- **Risk:** Low — requires active participation

**Example flow:**
```
User: "patch pihole"
Agent: [Searches r/Proxmox, CVE, your history]
       "Dry-run shows: [apt update && apt upgrade]. 
        Read these r/Proxmox threads? 
        [Run] [Show reasoning] [Ask community]"
User: Clicks [Run]
Agent: Takes snapshot first, then patches
```

---

### Level 2: **Maintain** ⚙ (Auto-Execute Safe Ops)
```
AGENT_AUTONOMY=2
```
- **What it can do:** 
  - Auto-apply patches (with pre-flight backup)
  - Restart failed services
  - Trigger backups
  - Create snapshots
  - Manage non-critical containers
- **What it CANNOT do:** 
  - Delete VMs/containers (still asks)
  - Modify network config
  - Change Proxmox host settings
  - Touch protected targets (unless `PVE_PROTECTION_MODE=warn`)
- **Use case:** Experienced users who want routine maintenance automated
- **Approval:** Guard checks + autonomy gates. User sees audit trail.
- **Risk:** Medium — requires trust in guard logic

**Example flow:**
```
User: "apply security patches to everything"
Agent: [Autonomy check: level 2 = allowed]
       [PVE protection: strict = snapshot required]
       Takes snapshot of pve
       Patches pihole, plex, etc. (one by one, with rollback snapshots)
       Reports: "✓ 12 patches applied, 0 failed, 4 security"
       Full audit log available
```

---

### Level 3: **Full** ⚡ (Autonomous Management)
```
AGENT_AUTONOMY=3
```
- **What it can do:** Everything (create, delete, modify, patch)
- **What it CANNOT do:** Nothing—full autonomy
- **Use case:** Advanced users on dev/test nodes **ONLY**
- **Approval:** None—agent decides and acts
- **Risk:** **HIGH** — only recommended for non-production

**Example flow:**
```
User: "optimize cluster for performance"
Agent: [Autonomy check: level 3 = full autonomy]
       Deletes old snapshots (freed 50GB)
       Creates 3 new test LXCs for load balancing
       Patches everything
       Rebalances VMs across nodes
       Reports: "Cluster optimized. 18 changes made."
       [User reviews audit log after the fact]
```

---

## 2. PVE PROTECTION MODES (Host-Level Protection — can we touch Proxmox itself?)

Set via `PVE_PROTECTION_MODE` env var:

### Mode: **strict** 🔒 (Block Host Changes)
```
PVE_PROTECTION_MODE=strict
```
- **Policy:** All writes to Proxmox host (pve, localhost) are **blocked**
- **What's protected:** `PROTECTED_TARGETS` (default: `pve localhost`)
- **Example:** `apply_patches(guest_name="pve")` returns "🔒 blocked"
- **Override:** Only by changing env var (requires restart)
- **Use case:** Production, shared homelabs, or when you want 100% protection

---

### Mode: **warn** ⚠️ (Allow With Pre-Flight Backup)
```
PVE_PROTECTION_MODE=warn
```
- **Policy:** Host writes are **allowed** but require:
  1. Audit log entry (WARN level)
  2. Pre-flight incremental PBS backup
  3. Explicit user confirmation or autonomy level ≥ 2
- **Example:** `apply_patches(guest_name="pve")` triggers backup, then applies patches
- **Rollback:** PBS restore available for last 24h
- **Use case:** Experienced users who want flexibility without total freedom

---

### Mode: **off** 🟢 (No Protection)
```
PVE_PROTECTION_MODE=off
```
- **Policy:** Host is treated like any other guest
- **What's protected:** Nothing (unless autonomy=0)
- **Use case:** Dev/test nodes, or experienced users who've disabled all guards
- **Risk:** **CRITICAL** — only use with autonomy ≥ 2

---

## Combined Security Matrix

| Autonomy | PVE Strict | PVE Warn | PVE Off |
|---|---|---|---|
| **0 (Observe)** | ✓✓✓ Safest | ✓✓✓ Safest | ✓✓✓ Safest |
| | Read-only always | Read-only always | Read-only always |
| **1 (Suggest)** | ✓✓ Safe | ✓✓ Safe | ✓ Moderate |
| | Can't touch host | Backups host, asks | Can modify host |
| **2 (Maintain)** | ✓ Moderate | ⚠️ Active | ⚠️ Active |
| | Guests auto-patch | Guests auto-patch | Everything auto-patch |
| | Host: blocked | Host: snapshot first | Host: snapshot first |
| **3 (Full)** | ✗ Broken | ✗ Risky | ✗✗✗ Maximum risk |
| | Can't run | Can do anything | Can do anything |
| | (Guard blocks all) | (Use with care) | (Prod: DON'T) |

---

## Recommended Security Postures

### 🔐 **Production / Shared Homelab**
```bash
AGENT_AUTONOMY=1              # Suggest mode—you click "Run"
PVE_PROTECTION_MODE=strict    # Host is untouchable
PRE_CHANGE_BACKUP=pbs         # Full PBS backup before any write
PROTECTED_TARGETS=pve localhost 192.168.1.10
```
**Philosophy:** Agent is a smart assistant, you're the final decision-maker.

---

### 🏠 **Personal Homelab (Experienced)**
```bash
AGENT_AUTONOMY=2              # Maintain mode—auto-patch guests
PVE_PROTECTION_MODE=warn      # Host allowed with backup first
PRE_CHANGE_BACKUP=snapshot    # Fast snapshots
```
**Philosophy:** Routine maintenance automated, risky ops still protected.

---

### 🧪 **Dev / Test Node**
```bash
AGENT_AUTONOMY=3              # Full autonomy
PVE_PROTECTION_MODE=warn      # Still take backups (good practice)
PRE_CHANGE_BACKUP=pbs         # Full backups for audit trail
PROTECTED_TARGETS=              # Optional—no hosts protected
```
**Philosophy:** Max automation, full audit trail for learning.

---

## How They Interact: Real Examples

### Example 1: User at Level 1 (Suggest), PVE Strict
```
User: "patch the host"
Guard: [PVE_PROTECTION_MODE=strict] → "Cannot patch pve"
Agent: "Host patching is blocked. Read these community discussions instead?
        If you want to allow it, set PVE_PROTECTION_MODE=warn"
```

### Example 2: User at Level 2 (Maintain), PVE Warn
```
User: [Cron: 2am] "apply patches automatically"
Autonomy: [Level 2] → patches allowed
Guard: [PVE_PROTECTION_MODE=warn] → backup first
Agent: Takes PBS incremental backup of pve
       Patches pve (kernel + security)
       Patches guests (pihole, homeassistant, etc.)
       Audit log: 18 operations, all reversible
```

### Example 3: User at Level 0 (Observe)
```
User: "optimize cluster"
Autonomy: [Level 0] → no writes allowed
Agent: "I'd recommend:
        1. Delete 5 old snapshots (would free 80GB)
        2. Migrate pihole to faster SSD
        3. Patch 3 guests
        
        You decide. Full reasoning here. r/Proxmox says...
        [Show reasoning] [Ask community] [View audit]"
User: Manually runs the optimizations
```

---

## Configuration

### Per-Environment

**Production:**
```bash
export AGENT_AUTONOMY=1
export PVE_PROTECTION_MODE=strict
export PRE_CHANGE_BACKUP=pbs
export PROTECTED_TARGETS="pve localhost prod-*.local"
```

**Development:**
```bash
export AGENT_AUTONOMY=2
export PVE_PROTECTION_MODE=warn
export PRE_CHANGE_BACKUP=snapshot
```

**Testing:**
```bash
export AGENT_AUTONOMY=3
export PVE_PROTECTION_MODE=warn
export PRE_CHANGE_BACKUP=pbs
```

### At Runtime (Settings UI)

All settings editable in Settings panel:
- Autonomy: 4-button segmented control (Observe / Suggest / Maintain / Full)
- PVE Protection: 3-button segmented control (Strict / Warn / Off)
- Pre-change backup: 3-button segmented control (None / Snapshot / PBS)
- All changes persist to `.env` via API

---

## Audit & Verification

### View Your Current Settings
```bash
# Agent reads these at startup
echo "AGENT_AUTONOMY=$AGENT_AUTONOMY"
echo "PVE_PROTECTION_MODE=$PVE_PROTECTION_MODE"
echo "PRE_CHANGE_BACKUP=$PRE_CHANGE_BACKUP"
echo "PROTECTED_TARGETS=$PROTECTED_TARGETS"
```

### Export Audit Log
```bash
# Via UI: [Audit panel] → [Download JSONL]
# Or via API:
curl http://127.0.0.1:8080/api/audit | jq '.' > audit-export.json
```

### Test the Guards
```bash
# Via API:
curl -X POST http://127.0.0.1:8080/api/chat \
  -d '{"message":"test_guard(operation=patch)"}' \
  | jq '.result'
```

---

## Migration Path: Starting Restrictive

1. **Day 1:** Autonomy=0, PVE Strict → learn the tool, read community discussions
2. **Week 1:** Autonomy=1, PVE Strict → routine queries, you approve patches
3. **Month 1:** Autonomy=2, PVE Warn → auto-patch guests, host protected
4. **Mature:** Autonomy=2, PVE Warn (prod) or Autonomy=3, PVE Warn (dev)

This progression builds confidence and muscle memory.
