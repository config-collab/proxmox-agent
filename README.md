# Proxmox Management Agent

**Decision-support AI for Proxmox infrastructure.** Replace GUI complexity with conversation, while staying in control. Security by design: you approve every change, full audit trail, multi-source verification.

> From an engineering background in CAD/PDM systems: this agent works like how AI replaced 10-click workflows with conversation—but for infrastructure. The difference: you stay in control. The agent proposes, you approve. Everything is logged.

---

## 🎯 What It Does

Ask in plain English. The agent:
- Queries your Proxmox environment (inventory, patches, backups, security)
- Consults official docs + community forums + CVE databases before recommending
- Shows reasoning and sources for every suggestion
- Requires your approval before executing changes
- Logs every operation with full audit trail
- Can rollback most changes via snapshots

**Examples:**
```
"Are my backups healthy?"
→ Checks last backup time, storage capacity, PBS status
→ Shows community discussions on backup strategies

"Patch pihole safely"
→ Searches for known issues, CVEs, forum experiences
→ Takes snapshot first, applies patches, keeps rollback available

"Run a security audit"
→ Scans open ports, SSH config, firewall rules, CVEs
→ Links to official hardening guides + community solutions
```

---

## 🔒 Security by Design

### Conservative Defaults
- **Level 1 (Suggest)** is the default — agent shows dry-run, you click to approve
- Host protection: Proxmox host writes are blocked by default
- Pre-flight backups: snapshots taken before risky changes
- Everything is logged and exportable

### Approval Workflow
```
User → Agent searches sources → Shows reasoning & dry-run → User clicks [Run]
  ↓
Pre-flight backup (snapshot/PBS) → Execute → Log outcome → Rollback available
```

You're never surprised. You see the full decision chain before it runs.

### Multi-Source Verification (Not Reddit Alone)
The agent consults 5 tiers of sources, ranked by reliability:

| Tier | Source | Weight | Authority |
|------|--------|--------|-----------|
| **1** | Official Proxmox docs | 3.0x | Ground truth |
| **2** | Proxmox forums (staff-moderated) | 2.0x | Peer-verified |
| **3** | Community scripts + curations | 1.5x | Maintained collections |
| **4** | Reddit discussions | 0.8x | Trends, sentiment |
| **5** | CVE databases (NIST, Debian, Ubuntu) | Critical override | Real-time threats |

Every recommendation shows which sources were consulted. You can click and verify.

### Audit Trail
Every operation logged in JSONL format:
```json
{
  "timestamp": "2026-06-03T14:32:15Z",
  "operation": "apply_patches",
  "target": "pihole-lxc",
  "autonomy_level": 1,
  "sources_consulted": [
    "pve.proxmox.com:pve-docs/chapter-patching.html",
    "forum.proxmox.com/threads/pihole-patches-12345"
  ],
  "reasoning": ["Official docs recommend monthly patching", "Forum: no recent failures"],
  "action": "executed",
  "result": "12 packages updated",
  "reversible": true,
  "rollback": "snapshot-pihole-20260603-143200"
}
```

Export anytime. Share with community if something breaks—they can see the full decision chain.

---

## 🏗️ Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Server (server.py)                                 │
│  - SSE streaming for real-time UI updates                   │
│  - Tool dispatching & autonomy gating                       │
│  - Settings & audit API endpoints                           │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  LLM Integration (llm.py)                                    │
│  - Claude Sonnet for reasoning + extended thinking          │
│  - Tool use with safety gates                               │
│  - Reasoning chain generation                               │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  26 Tools (tools/*.py)                                       │
│  - Inventory, patch, backup, networking, snapshots          │
│  - Security audit, CVE lookup, helper scripts               │
│  - Community search (Reddit, forums)                        │
│  - Audit log export, reasoning traces                       │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  RAG System (docs/*.py)                                      │
│  - BM25 search over Proxmox docs + environment state        │
│  - Forum RSS + real-time API                                │
│  - CVE database (NIST NVD v2)                               │
│  - Reddit search via official API                           │
│  - Helper scripts indexing                                  │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  Proxmox Integration                                         │
│  - API calls (proxmox_api.py)                               │
│  - SSH for guest execution (ssh_client.py)                  │
│  - Audit logging (audit.py)                                 │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  Web UI (gui/)                                               │
│  - Vanilla JS, dark/light themes                            │
│  - Real-time SSE streaming                                  │
│  - Settings panel (autonomy, protection, provider)          │
│  - Audit log viewer                                         │
│  - PWA support (installable)                                │
└─────────────────────────────────────────────────────────────┘
```

### Security Gates

```
Request → Config check
         ↓
         Autonomy level gate (is this tool allowed at current level?)
         ↓
         PVE protection gate (is this a protected target?)
         ↓
         Pre-flight backup gate (snapshot/PBS before writes?)
         ↓
         Execute + log
         ↓
         Audit entry (with sources, reasoning, outcome, reversibility)
```

### Autonomy Levels

| Level | Name | Use Case | Approval Required |
|-------|------|----------|------------------|
| **0** | Observe | Read-only exploration | No (can't write) |
| **1** | Suggest | Default—drafts shown | Click [Run] for each op |
| **2** | Maintain | Auto-patch guests | Pre-flight backups |
| **3** | Full | Autonomous management | None (dev/test only) |

---

## 🚀 Deployment

### Option 1: BananaPi / Raspberry Pi (Recommended)

Minimal footprint (150MB), runs alongside voice assistant or other services.

```bash
# 1. Clone repo
git clone https://github.com/your-username/proxmox-agent.git
cd proxmox-agent

# 2. Copy .env template and configure
cp .env.example .env
# Edit .env with your Proxmox host, API token, SSH keys path

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run server
python3 server.py

# 5. Open http://192.168.x.x:8080 in browser
```

**SSH Key Setup:**
```bash
# Generate SSH key for Proxmox access
ssh-keygen -t ed25519 -f ~/.proxmox-agent/keys/proxmox_id_ed25519 -C "proxmox-agent"

# Copy public key to Proxmox host
ssh-copy-id -i ~/.proxmox-agent/keys/proxmox_id_ed25519.pub root@192.168.x.x

# Verify
ssh -i ~/.proxmox-agent/keys/proxmox_id_ed25519 root@192.168.x.x pveversion
```

### Option 2: Proxmox LXC (Via Helper Script)

One-click installation directly on your Proxmox node.

```bash
# On Proxmox host:
bash -c "$(curl -fsSL https://raw.githubusercontent.com/your-username/proxmox-agent/main/ct-proxmox-agent.sh)"
```

The script:
- Creates unprivileged LXC (Debian 12)
- Installs dependencies
- Configures API token
- Starts systemd service
- Runs daily cron jobs for inventory/patch/security checks

### Option 3: Standalone Docker / VM

```bash
docker run -d \
  -p 8080:8080 \
  -e PROXMOX_HOST=192.168.x.x \
  -e PROXMOX_API_TOKEN=your-token \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v ~/.proxmox-agent/keys:/root/.proxmox-agent/keys:ro \
  your-username/proxmox-agent:latest
```

---

## ⚙️ Configuration

### Required
```env
PROXMOX_HOST=192.168.x.x              # Your Proxmox node IP
PROXMOX_API_TOKEN=PVEAPIToken=...     # From Datacenter → Permissions → API Tokens
SSH_HOST=192.168.x.x                  # Same as PROXMOX_HOST (usually)
SSH_KEYS_DIR=~/.proxmox-agent/keys    # Where SSH keys live
```

### LLM Provider (Choose One)
```env
# Claude (recommended)
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...          # https://console.anthropic.com

# OR OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# OR local (Ollama)
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
```

### Security Settings
```env
# Start conservative, graduate to higher levels
AGENT_AUTONOMY=1                      # 0=observe, 1=suggest, 2=maintain, 3=full
PVE_PROTECTION_MODE=strict            # strict, warn, off
PRE_CHANGE_BACKUP=snapshot            # none, snapshot, pbs
PROTECTED_TARGETS=pve localhost       # Never touched in strict mode
```

### Optional
```env
BACKUP_STORAGE=local-pbs              # PBS storage target
PBS_HOST=192.168.x.x                  # PBS server IP (if different)
NTFY_URL=https://ntfy.sh/your-topic   # Push notifications
```

See [`.env.example`](.env.example) for full documented template.

---

## 📖 Usage Guide

### Web UI
1. Open http://192.168.x.x:8080
2. Click **⚙️ Settings** to configure security level, protection mode, LLM provider
3. Type your request in the chat box at the bottom
4. See reasoning, sources, dry-run
5. Click **[Run]** to approve, or **[Show reasoning]** for details

### Example Requests

**Health Check**
```
"Run a full health check"
→ Checks inventory, patches, backups, security in parallel
→ Returns summary card with health status
```

**Patch with Community Verification**
```
"Are there any security patches I should worry about?"
→ Searches CVE database + official docs + forums
→ Shows severity, patch availability, community experiences
→ Dry-run: apt update && apt upgrade (pihole-lxc)
→ You decide: [Run] / [Ask community] / [Defer]
```

**Security Audit**
```
"Run a security audit"
→ Scans: open ports, SSH config, firewall, CVEs, weak passwords
→ Returns: [CRITICAL], [HIGH], [MEDIUM], [INFO] findings
→ Each links to hardening guide + community discussion
```

**Community Lookup**
```
"What do people say about backing up on ZFS?"
→ Searches r/Proxmox + Proxmox forums
→ Shows: thread titles, upvotes, timestamps
→ Summarizes consensus (ZFS + incremental backup strategy = recommended)
```

### Keyboard Shortcuts
- `Ctrl+Shift+R` – Refresh browser (clears cache)
- `Cmd/Ctrl+K` – New chat

### Settings Panel

**Security Level**
- **Observe**: Read-only (best for learning)
- **Suggest**: You approve each action (recommended for production)
- **Maintain**: Auto-patch guests, pre-flight backups (advanced users)
- **Full**: Autonomous (dev/test only)

**PVE Protection**
- **Strict**: Block host writes (safest)
- **Warn**: Allow with pre-flight backup
- **Off**: No protection (dev/test)

**Pre-Change Backup**
- **None**: No backup before changes
- **Snapshot**: Fast rollback (default)
- **PBS**: Full incremental backup (slowest, safest)

**LLM Provider**
- Swap between Claude, OpenAI, Ollama at runtime
- Costs differ; Claude Sonnet recommended for reasoning

---

## 🛠️ Tools (26 Total)

### Inventory & Status
- `get_inventory()` – List all VMs/LXCs with IPs
- `get_tasks()` – Recent Proxmox tasks
- `get_metrics()` – CPU/RAM/storage trends

### Patching
- `check_patches()` – Security + routine updates pending
- `apply_patches()` – Apply with pre-flight backup
- `compare_with_community()` – What users say about this patch

### Backup & Recovery
- `check_backups()` – Health report (age, coverage, overdue)
- `check_pbs()` – Proxmox Backup Server status
- `run_backup_now()` – Trigger backup, wait for completion

### VM/LXC Management
- `manage_vm()` – Start, stop, restart, status
- `manage_snapshots()` – List, create, rollback, delete
- `create_container()` – LXC provisioning with dry-run

### Networking & Security
- `search_docs()` – Proxmox official docs
- `search_forum()` – Proxmox community forums
- `search_cve()` – CVE database (NIST NVD)
- `ask_community()` – r/Proxmox discussion
- `search_all_sources()` – Unified search (all 5 tiers)
- `compare_with_all_sources()` – Pre-flight consensus check

### Helpers
- `search_helper_scripts()` – Community-scripts.org
- `trending_proxmox()` – What's hot on r/Proxmox

### Audit & Transparency
- `show_reasoning()` – Full decision chain
- `audit_log_export()` – JSON/CSV/Markdown export
- `check_pve_protection()` – Current security settings
- `test_guard()` – Simulate guard logic

---

## 🔐 Trust & Transparency

### For Skeptics
> *"I wouldn't trust AI with my infrastructure."*

**Our answer:**
1. **Not autonomous** – Decision-support tool. You approve every write.
2. **Multi-source** – Consults official docs before Reddit.
3. **Auditable** – Full decision log. Community can help if something breaks.
4. **Reversible** – Snapshots before risky changes.
5. **Bounded** – Host protection prevents accidental PVE breakage.

### How It's Different
- ❌ "Fire and forget automation" → ✅ "You approve every change"
- ❌ "Black-box reasoning" → ✅ "Full decision chain shown"
- ❌ "Reddit-only advice" → ✅ "Official docs checked first"
- ❌ "No rollback" → ✅ "Snapshots + PBS backups"
- ❌ "Autonomous mistakes" → ✅ "Human-in-loop decisions"

See [**SECURITY_LEVELS.md**](SECURITY_LEVELS.md) for detailed security framework.

See [**TRUST_ARCHITECTURE.md**](TRUST_ARCHITECTURE.md) for addressing skepticism with evidence.

See [**KNOWLEDGE_SOURCES.md**](KNOWLEDGE_SOURCES.md) for how sources are ranked and verified.

---

## 📊 Performance

| Metric | Target | Notes |
|--------|--------|-------|
| Chat response latency | <2s | SSE streaming from LLM |
| Tool execution | <30s | Most ops (patch, backup, snapshot) |
| Memory footprint | <300MB | On BananaPi (1GB RAM total) |
| Startup time | <5s | FastAPI server ready |

---

## 🐛 Troubleshooting

### Server Won't Start
```bash
# Check imports
python3 -c "import fastapi; import anthropic; print('OK')"

# Check config
cat .env | grep PROXMOX_HOST

# Check logs
tail -20 /tmp/server.log
```

### Can't Connect to Proxmox
```bash
# Test API access
curl -k https://192.168.x.x:8006/api2/json/version

# Test SSH
ssh -i ~/.proxmox-agent/keys/proxmox_id_ed25519 root@192.168.x.x pveversion
```

### Patches Won't Apply
```bash
# Check autonomy level (must be ≥ 2)
echo "AGENT_AUTONOMY=$AGENT_AUTONOMY"

# Check PVE protection (strict mode blocks host patches)
echo "PVE_PROTECTION_MODE=$PVE_PROTECTION_MODE"

# View audit log
tail -20 ~/.proxmox-agent/audit.jsonl
```

### No CVE Results
```bash
# Check internet connectivity
curl https://nvd.nist.gov/

# Check rate limits (NIST has limits)
# If hit, wait 1 hour before retry
```

---

## 📝 Documentation

- [**SECURITY_LEVELS.md**](SECURITY_LEVELS.md) – Autonomy levels, PVE protection, pre-change backups
- [**TRUST_ARCHITECTURE.md**](TRUST_ARCHITECTURE.md) – Addressing skeptics, audit trails, reversibility
- [**KNOWLEDGE_SOURCES.md**](KNOWLEDGE_SOURCES.md) – How 5 tiers work, why Reddit is last
- [**CLAUDE.md**](CLAUDE.md) – Original system prompt (for Claude Code integration)

---

## 🤝 Contributing

This project is MIT licensed. Contributions welcome!

**Areas for help:**
- Community feedback on security design
- Testing on different Proxmox versions
- New tools (network config, firewall rules, HA setup)
- MCP server wrapper for Cursor IDE / other Claude clients
- Localization

---

## 📄 License

MIT License. See LICENSE file for details.

---

## 🙋 FAQ

**Q: Is this really safe?**
A: Conservative defaults (read-only by default), approval required, pre-flight backups, full audit trail, multi-source verification. See SECURITY_LEVELS.md.

**Q: Can it break my Proxmox host?**
A: Host protection is on by default (can't touch PVE). You'd need to explicitly set `PVE_PROTECTION_MODE=warn` or `off`, then approve the action.

**Q: What if something goes wrong?**
A: Snapshots + PBS restore available. Full audit log shows what happened and why. Community can help because they see the reasoning.

**Q: Does it require internet?**
A: Local docs are cached. Community search (Reddit, forums) needs internet. CVE database needs internet. LLM API calls need internet.

**Q: Can I run this on my Proxmox host?**
A: Yes, via the LXC helper script. Or on a Pi/BananaPi alongside your voice assistant. Or in Docker.

**Q: What about privacy?**
A: No data leaves your network except: LLM API calls (code + reasoning), CVE queries (package names), community search (search terms). All configurable.

---

## 🎯 Roadmap

- [x] Core agent + 26 tools
- [x] Multi-source RAG (docs + forums + CVE + Reddit)
- [x] Security framework (autonomy + protection modes)
- [x] Audit logging + reasoning traces
- [x] Web UI + PWA support
- [ ] MCP server wrapper (for Cursor IDE)
- [ ] Helm chart for Kubernetes
- [ ] Ansible module for fleet management
- [ ] Integration with Proxmox metrics (Prometheus)
- [ ] Backup auto-recovery (PBS restore on alert)

---

## 👋 Support

- **Issues**: GitHub issues
- **Discussions**: GitHub discussions
- **Community**: r/Proxmox

---

**Built with ❤️ for infrastructure engineers who prefer conversation to clicks.**
