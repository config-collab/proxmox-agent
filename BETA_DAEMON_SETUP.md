# Beta Daemon Setup Guide

**Status:** BETA/EXPERIMENTAL

This lightweight daemon runs 24/7 and monitors your Proxmox infrastructure without making any changes. It only **detects issues and sends alerts**.

---

## What It Does

✅ **Monitors (Every 60 seconds):**
- Disk capacity across all datastores
- Backup health (last backup age per VM)
- PBS status (GC failures, disk usage)
- Critical PVE services (pveproxy, pvedaemon, pvestatd)

✅ **Alerts (Rate-Limited):**
- Sends ntfy notifications when issues detected
- Rate-limits alerts to avoid spam (max once per hour per issue)
- Logs all findings to audit trail

❌ **Never Modifies Anything:**
- No autonomous fixes
- No automatic restarts
- No configuration changes
- 100% read-only operation

---

## Installation (5 minutes)

### Step 1: Enable in .env

```bash
cd ~/.proxmox-agent
echo "DAEMON_ENABLED=1" >> .env
```

### Step 2: Configure Alerts (Optional)

```bash
# Set ntfy.sh URL for notifications (highly recommended)
echo "NTFY_URL=https://ntfy.sh/my-proxmox-alerts" >> .env

# Customize thresholds (defaults shown):
echo "DAEMON_ALERT_THRESHOLD_DISK=85" >> .env          # % full before alert
echo "DAEMON_ALERT_BACKUP_AGE_HOURS=24" >> .env        # Hours before alert
echo "DAEMON_CHECK_INTERVAL=60" >> .env                # Seconds between checks
```

### Step 3: Test It

```bash
# Run once to verify it works
python daemon.py --once

# Expected output:
# [info] Running checks once...
# [info] Check results:
#   ✅ disk_capacity: ok
#   ✅ backup_health: ok
#   ✅ pbs_health: ok
#   ✅ critical_services: ok
```

### Step 4: Start as Background Service (Choose One)

#### Option A: systemd (Recommended - Linux only)

Create `/etc/systemd/system/proxmox-daemon.service`:

```ini
[Unit]
Description=Proxmox Agent Daemon (BETA)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=root
WorkingDirectory=/root/.proxmox-agent
ExecStart=/usr/bin/python3 /root/.proxmox-agent/daemon.py
Restart=on-failure
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=proxmox-daemon

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable proxmox-daemon
sudo systemctl start proxmox-daemon

# Verify it's running
sudo systemctl status proxmox-daemon

# View logs
sudo journalctl -u proxmox-daemon -f
```

#### Option B: Manual (Any OS)

```bash
# In a screen/tmux session:
screen -S proxmox-daemon
cd ~/.proxmox-agent
python daemon.py

# Detach: Ctrl-A then Ctrl-D
# Resume: screen -r proxmox-daemon
```

#### Option C: Cron (Runs every minute - less efficient)

```bash
# Add to crontab (every minute)
* * * * * cd ~/.proxmox-agent && /usr/bin/python3 daemon.py --once
```

---

## Usage

### View Live Logs

```bash
# If using systemd:
sudo journalctl -u proxmox-daemon -f

# If using screen:
screen -r proxmox-daemon

# Raw daemon log:
tail -f ~/.proxmox-agent/daemon.log
```

### View Alerts

```bash
# Check ntfy.sh alerts:
curl https://ntfy.sh/my-proxmox-alerts

# Or view in browser:
# https://ntfy.sh/my-proxmox-alerts

# Check audit log:
tail -20 ~/.proxmox-agent/.operations/audit.jsonl
```

### Stop Daemon

```bash
# If using systemd:
sudo systemctl stop proxmox-daemon

# If using screen:
screen -r proxmox-daemon
# Then: Ctrl-C

# Kill if hung:
pkill -f "daemon.py"
```

---

## Configuration Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `DAEMON_ENABLED` | `0` | Set to `1` to enable daemon |
| `NTFY_URL` | (none) | ntfy.sh topic for alerts |
| `DAEMON_CHECK_INTERVAL` | `60` | Seconds between checks |
| `DAEMON_ALERT_THRESHOLD_DISK` | `85` | Alert when datastore >85% full |
| `DAEMON_ALERT_BACKUP_AGE_HOURS` | `24` | Alert if backup older than 24h |
| `DAEMON_ALERT_PBS_DISK_RATE` | `20` | Alert if PBS fills >20% per day |

### Alert Examples

```
📊 Disk usage check found problems:
  🟠 /var/lib/vz: 87% (WARNING)
  🔴 /mnt/datastore: 95% (CRITICAL)

📧 Backup health check found problems:
  • VM 100: no_backup_found
  • VM 102: backup 36 hours old

🔧 PBS health check found problems:
  • Garbage collection failed
  • Backup disk: 92% full
```

---

## What's NOT Included (By Design)

This daemon is **intentionally minimal** for the beta:

- ❌ No autonomous fixes (all changes require approval via GUI)
- ❌ No learning from patterns (analyze_audit.py is separate)
- ❌ No community knowledge search (available in interactive GUI)
- ❌ No scheduled operations (cron handles those)

**Why?** Beta should be **low-risk**. We monitor + alert. You approve fixes.

---

## Feedback: Help Shape the Future

The daemon is **EXPERIMENTAL**. Community feedback drives improvements:

1. **Is it useful?** ("Love the disk alerts!")
2. **Too noisy?** ("Getting alerts too often")
3. **Missing checks?** ("Should also monitor X")
4. **Want auto-fixes?** ("For low-risk operations like disk cleanup")

**Report feedback:**
- GitHub Issues: https://github.com/your-repo/issues
- Reddit: r/Proxmox
- Email: your-email@proxmox

---

## Roadmap: What's Next (Based on Beta Feedback)

**Phase 1 (Current):** Read-only monitoring + alerts
- ✅ Disk, backup, PBS, service checks
- ✅ Real-time alerts (ntfy)
- ✅ Rate-limited to avoid spam
- ✅ Zero modifications

**Phase 2 (If Community Wants):** Autonomous low-risk fixes
- 🔲 Auto-cleanup old snapshots (if disk>90%)
- 🔲 Auto-restart failed services (if down >5 min)
- 🔲 Auto-trigger backup if >24h old
- All with reversibility + audit log

**Phase 3 (If Successful):** Learning + optimization
- 🔲 Analyze audit logs weekly
- 🔲 Suggest composite tools
- 🔲 Predict capacity limits
- 🔲 Optimize check frequency

---

## Troubleshooting

### Daemon won't start

```bash
# Check Python is working
python3 --version

# Check .env is readable
cat ~/.proxmox-agent/.env | head -5

# Run with debug output
python daemon.py --debug

# Check SSH keys exist
ls -la ~/.ssh/id_ed25519
```

### SSH connection fails

```bash
# Test SSH to Proxmox
ssh -i ~/.ssh/id_ed25519 root@192.168.1.10 "pveversion"

# Test SSH to PBS (if configured)
ssh -i ~/.ssh/pbs_id_ed25519 root@192.168.0.244 "proxmox-backup-manager version"
```

### Not getting alerts

```bash
# Verify NTFY_URL is set
grep NTFY_URL ~/.proxmox-agent/.env

# Test ntfy connectivity
curl -d "test" https://ntfy.sh/my-proxmox-alerts

# Check daemon is running
ps aux | grep daemon.py
```

### Daemon uses too much CPU

```bash
# Increase check interval (default 60s)
echo "DAEMON_CHECK_INTERVAL=300" >> ~/.proxmox-agent/.env

# Restart
sudo systemctl restart proxmox-daemon
```

---

## Security & Privacy

- ✅ **Read-only:** Daemon only reads, never modifies
- ✅ **Local only:** Doesn't phone home or cloud anything
- ✅ **Audited:** Every action logged to audit.jsonl
- ✅ **SSH keys:** Uses same SSH keys as interactive agent
- ✅ **Open source:** Code is visible, reviewable
- ⚠️ **ntfy.sh alerts:** Sent to ntfy.sh (can be self-hosted if privacy concern)

---

## Uninstall

If you want to remove the daemon:

```bash
# Stop the service
sudo systemctl stop proxmox-daemon
sudo systemctl disable proxmox-daemon

# Remove service file
sudo rm /etc/systemd/system/proxmox-daemon.service
sudo systemctl daemon-reload

# Disable in .env
sed -i 's/DAEMON_ENABLED=1/DAEMON_ENABLED=0/' ~/.proxmox-agent/.env

# View logs remain at ~/.proxmox-agent/daemon.log for debugging
```

---

## Next: Improvements #1-5

Once daemon is running, enable these enhancements in the GUI:

1. **Daily Health Check** (improvement #1)
   - Replaces simple inventory with comprehensive report
   - Run via cron: `0 3 * * * python main.py --no-llm`

2. **Risk-Aware Approvals** (improvement #2)
   - Shows risk level + rollback steps before you approve
   - Auto-enabled in GUI when features enabled

3. **Weekly Insights** (improvement #3)
   - Analyzes audit logs for patterns
   - Suggests optimizations

4. **Feedback Collection** (improvement #4)
   - Rate tools (1-5 stars)
   - Help agent learn what's useful

5. **Community Knowledge** (improvement #5)
   - Show Reddit/forum discussions for your problem
   - Get battle-tested solutions

---

## Questions?

Check the main docs:
- `IMPROVEMENT_PRIORITIES.md` — How improvements work
- `PRAGMATIC_AUTONOMY.md` — Risk classification approach
- `CURRENT_REALITY_VS_VISION.md` — Architecture overview
- `CLAUDE.md` — Main system prompt

Or ask in the interactive agent!
