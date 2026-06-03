# Current Reality vs. Vision: Does Your Agent Actually Run at Night?

**The honest answer: No. Not yet.**

Your agent right now is **interactive only**. It doesn't run in the background detecting issues at 3 AM. All the frameworks you have documented (Pragmatic Autonomy, Feature Learning, etc.) are **blueprints for what you COULD build**, not what's currently running.

---

## What You Have TODAY

### server.py (Web UI)
```
User → Opens browser → http://192.168.0.235:8080
         ↓
      FastAPI server
         ↓
   Serves GUI + chat endpoint
         ↓
    When user types: runs agent interactively
         ↓
    When user closes browser: stops running
```

**Reality:** Server only responds when you're actively using it.

### main.py (CLI)
```
User → Runs: python main.py
         ↓
      Agent starts
         ↓
   Runs interactive chat loop
         ↓
   Waits for your input
         ↓
   When you type "exit": stops
```

**Reality:** Only active while you have terminal open.

### Cron/Headless Mode (--no-llm)
```
Cron job: 0 3 * * * python main.py --no-llm
           ↓
    3 AM: Agent wakes up
           ↓
    Runs: inventory + security scan + patch check
           ↓
    Sends ntfy alert if critical findings
           ↓
    Exits (doesn't keep running)
```

**Reality:** Runs on a schedule, but only checks — doesn't actively monitor or fix.

---

## What You ENVISIONED (In the Documentation)

```
Agent is running 24/7:
- Detects disk fills in real-time
- Fixes permission errors autonomously
- Monitors backups continuously
- Learns from patterns
- Acts without you asking
```

**Reality:** This doesn't exist yet.

---

## The Gap

| Aspect | What You Have | What You Need |
|--------|---|---|
| **Always-on monitoring** | ❌ Stops when you exit | ✅ Continuous daemon process |
| **Autonomous detection** | ❌ Only checks on cron schedule | ✅ Real-time event loop |
| **Autonomous fixes** | ❌ Can't execute without approval | ✅ Can apply low-risk fixes automatically |
| **Learning from patterns** | ❌ Just collects audit logs | ✅ Analyzes logs + suggests improvements |
| **3 AM response** | ❌ Takes time to query + fix | ✅ Instant detection + action |

---

## Why the Gap Exists

### It's Actually Complex to Build

To go from "interactive agent" to "always-on autonomous agent" requires:

1. **Background daemon** that never stops
   - Current: server.py is a web UI for *your* requests
   - Needed: daemon that runs independently

2. **Real-time monitoring hooks**
   - Current: checks on schedule (cron)
   - Needed: subscribes to Proxmox events, watches logs live

3. **Risk classifier + autonomy gates**
   - Current: documented in PRAGMATIC_AUTONOMY.md but not implemented
   - Needed: actual code that decides "is this safe to fix alone?"

4. **Approval/escalation system**
   - Current: doesn't exist
   - Needed: way to ask you when uncertain (via push notification, email, etc)

5. **State management**
   - Current: stateless (each run is fresh)
   - Needed: remember what you approved, what failed, what's in progress

6. **Persistence layer**
   - Current: audit logs are append-only
   - Needed: database to track incidents, patterns, learned behaviors

---

## The Honest Reality Check

### Your three options:

### Option 1: Keep Current Setup (Simple, Limited)
```
What you have:
- Web UI for interactive use
- Cron job for daily checks
- Manual approvals needed
- Good for when you're actively managing things

Pro: Simple, safe, working
Con: Misses 3 AM problems
     Requires your approval for everything
     No autonomous fixes
```

**Best for:** Homelab where you're actively monitoring.

---

### Option 2: Upgrade to Always-On Daemon (Medium Effort)
```
What you'd build:
- Background process that never stops
- Watches Proxmox events in real-time
- Monitors key metrics (disk, backup status, etc)
- Can execute low-risk fixes autonomously
- Escalates uncertain issues to you

Pro: Detects 3 AM problems
     Fixes obvious ones automatically
     Still asks you on risky operations
Con: More complex code
     Requires proper daemon setup
     Need notification system
     Testing is harder

Time to implement: 2-3 weeks
```

**Best for:** Production homelab where reliability matters.

---

### Option 3: Hybrid (What Most People Do)
```
What you'd build:
- server.py stays as interactive web UI (for your requests)
- Add a separate daemon for background monitoring
- They communicate via shared audit log + notification system
- Daemon handles: disk monitoring, backup verification, security alerts
- Web UI handles: complex decisions, manual operations

Pro: Best of both
     You still have control via web UI
     Daemon handles routine monitoring
     Clear separation of concerns
Con: Two systems to manage
     More code to maintain
```

**Best for:** Advanced setups.

---

## What Would It Take To Do Option 2 (Always-On)?

### Phase 1: Background Daemon (1 week)
```python
# New file: daemon.py
class ProxmoxDaemon:
    def __init__(self):
        self.running = True
        self.config = load_config()
    
    async def run_forever(self):
        """Main loop — runs until killed."""
        while self.running:
            await self.check_health()
            await self.check_backups()
            await self.check_security()
            await asyncio.sleep(60)  # Check every minute
    
    async def check_health(self):
        """Monitor disk, CPU, memory — autonomous fixes on low-risk."""
        disk = await self.proxmox.get_disk_usage()
        if disk > 90:
            self.escalate("Disk at 90%", risk="high")
        elif disk > 85:
            await self.cleanup_snapshots()  # Auto-fix: safe
    
    async def check_backups(self):
        """Verify backups completed; alert if any >24h old."""
        backups = await self.proxmox.get_recent_backups()
        for vm, last_backup in backups.items():
            age_hours = (now - last_backup).total_seconds() / 3600
            if age_hours > 24:
                self.escalate(f"VM {vm} backup {age_hours}h old")
    
    async def check_security(self):
        """Run security audit, alert on critical findings."""
        findings = await self.security_audit()
        for finding in findings:
            if finding['severity'] == 'CRITICAL':
                self.escalate(finding)
```

### Phase 2: Risk Classifier (1 week)
```python
# In guard.py or autonomy.py
class ActionRiskClassifier:
    def classify(self, operation: str, target: str) -> RiskLevel:
        """Decide: can agent do this alone, or ask user?"""
        
        rules = {
            "cleanup_snapshots": ("reversible_isolated", 1),
            "restart_service": ("reversible_isolated", 1),
            "apply_patch": ("reversible_cascading", 2),
            "delete_vm": ("irreversible", 3),
            "change_network": ("irreversible", 3),
        }
        
        risk_class, autonomy_needed = rules.get(operation, ("unknown", 99))
        user_autonomy = int(os.environ.get("AGENT_AUTONOMY", 1))
        
        # If user allows this risk level, agent can decide alone
        return risk_class if user_autonomy >= autonomy_needed else "escalate"
```

### Phase 3: Notification System (3 days)
```python
# In notify.py
class Notifier:
    async def alert(self, severity: str, title: str, message: str):
        """Send alert via ntfy/email/Slack — ask for approval if needed."""
        
        if severity == "CRITICAL" and self.needs_approval:
            # Send ntfy with action buttons
            # "Fix It" / "Wait" / "Never This"
            approval = await self.wait_for_approval(timeout=300)
            if approval:
                await self.execute_fix()
```

### Phase 4: Systemd Service (2 days)
```ini
# /etc/systemd/system/proxmox-daemon.service
[Unit]
Description=Proxmox Agent Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/user/.proxmox-agent
ExecStart=/usr/bin/python3 daemon.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
systemctl daemon-reload
systemctl enable proxmox-daemon
systemctl start proxmox-daemon
```

### Phase 5: Testing (1 week)
```
- Unit tests for risk classifier
- Integration tests with Proxmox sandbox
- Load tests (can it handle 1000 events/hour?)
- Failure tests (what happens if Proxmox goes down?)
- Rollback tests (can we revert a bad autonomous fix?)
```

---

## The Real Question: What Should YOU Do?

### If you run a homelab and sleep well now:
✅ **Keep current setup.** Interactive + daily cron checks = good enough.

### If you've had 3 AM problems:
⚠️ **Add always-on monitoring.** But start small:
- Add daemon for disk monitoring only
- Add notification for backup failures
- Manually approve fixes for first month
- Then add autonomous cleanup

### If you want "set it and forget it":
🚀 **Build Option 2 (always-on daemon).** But:
- Start with read-only monitoring (no fixes yet)
- Add dry-run approval before any fixes
- Test heavily in sandbox first
- Gradually increase autonomy level

---

## The Decision Tree

```
Do you want agent running at 3 AM?
├─ NO → Use current setup (interactive + cron)
│      You're good!
│
└─ YES → Do you want it to fix things alone?
   ├─ NO → Add monitoring daemon (reads logs, sends alerts)
   │       User still approves all fixes
   │       Time: 1 week
   │       Effort: Medium
   │
   └─ YES → Build full autonomy (daemon + risk classifier + fixes)
            User only intervenes for risky operations
            Time: 4-6 weeks
            Effort: High
```

---

## The Honest Assessment

| Goal | Your Status | Effort to Achieve |
|------|---|---|
| "Agent monitors disk at 3 AM and alerts me" | ❌ Not implemented | 3-5 days |
| "Agent detects backup failure and fixes it" | ❌ Not implemented | 1-2 weeks |
| "Agent learns from patterns and suggests improvements" | 🟡 Documented, not coded | 2-3 weeks |
| "Agent handles routine ops autonomously" | ❌ Not implemented | 4-6 weeks |
| "I can check a web UI to see everything" | ✅ Working (server.py) | Already done |

---

## My Recommendation

**Start here (this week):**

1. Keep server.py as-is (it works)
2. Add a lightweight daemon that:
   - Checks disk, backup age, PBS status every 60 seconds
   - Sends push notifications (ntfy) for problems
   - Stores findings in audit log
   - **Does NOT fix anything autonomously yet**

**Time cost:** 3-5 days
**Benefit:** Sleep better (know when 3 AM problems happen)
**Risk:** Low (read-only, just monitoring)

**Then evaluate (in 2 weeks):**
- Did you get useful alerts?
- Did any incidents happen that you wish were auto-fixed?
- Are you ready to let agent fix low-risk operations?

**Then decide (month 2):**
- Add autonomy for specific low-risk operations (disk cleanup, restart failed service, etc)
- Use risk classifier to decide what needs your approval
- Test thoroughly before enabling

---

## TL;DR

**Current state:** Agent runs when you ask (interactive) + daily checks (cron). No 3 AM response.

**Vision state:** Agent runs 24/7, detects issues, fixes low-risk ones autonomously.

**Gap:** ~4-6 weeks of work to bridge it.

**My recommendation:** Start with read-only monitoring (1 week), then add low-risk fixes (2 weeks). Build incrementally, test at each step.

What do you want to do?
