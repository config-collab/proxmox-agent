# Improvement Priorities Within Current Architecture

Staying with **interactive GUI + daily cron checks**. What can you improve RIGHT NOW without building a daemon?

---

## Current Architecture (Unchanged)

```
You (User)
  ↓
server.py (Web UI)  +  main.py --no-llm (Daily Cron)
  ↓
Tools (read-only diagnostics + optional fixes with approval)
  ↓
Proxmox + PBS
```

**What stays the same:**
- Web UI for interactive use
- Daily cron for automated checks
- You approve all fixes
- No background daemon

**What can improve:**
- Better cron detection
- Smarter approval workflows
- Better feedback collection
- Learning from audit logs
- Faster problem diagnosis
- Community knowledge integration

---

## Improvement #1: Better Cron Health Checks (2 days)

**What you have now:**
```bash
# Daily at 3 AM:
python main.py --no-llm
  ├─ Run inventory
  ├─ Run security audit (superficial)
  ├─ Check patches
  └─ Send ntfy alert if critical
```

**Problems:**
- ❌ Only checks 3 things
- ❌ Doesn't verify backups are healthy
- ❌ Doesn't catch PBS issues early
- ❌ Alert tells you there's a problem but not what to do

**Improvement: Comprehensive Daily Health Report**

```python
# New file: tools/daily_health_check.py

@tool(
    name="daily_health_check",
    description="Complete health report for cron: backups, disk, security, services",
    input_schema={"type": "object", "properties": {}, "required": []}
)
def daily_health_check() -> str:
    """
    Run at 3 AM daily. Returns structured report for ntfy alert.
    """
    report = {
        "timestamp": datetime.now().isoformat(),
        "status": "healthy",  # or "warning" or "critical"
        "checks": {},
    }
    
    # Check 1: Disk usage across all datastores
    disk = check_disk_capacity()
    report["checks"]["disk"] = disk
    if disk["status"] == "critical":
        report["status"] = "critical"
    
    # Check 2: Recent backups (last 24h for prod, 7d for dev)
    backups = check_backup_health()
    report["checks"]["backups"] = backups
    if backups["failed_count"] > 0:
        report["status"] = "critical" if backups["prod_failed"] else "warning"
    
    # Check 3: PBS health (GC status, disk fill rate, replication)
    pbs = check_pbs_health()
    report["checks"]["pbs"] = pbs
    if pbs["gc_failed"] or pbs["disk_fill_rate"] > 20:  # 20% per day
        report["status"] = "critical"
    
    # Check 4: Security findings (brief)
    sec = check_security_brief()
    report["checks"]["security"] = sec
    if sec["critical_count"] > 0:
        report["status"] = "critical"
    
    # Check 5: Running services health
    services = check_critical_services()
    report["checks"]["services"] = services
    if services["any_failed"]:
        report["status"] = "critical"
    
    # Format for ntfy alert
    summary = format_ntfy_alert(report)
    audit.log("daily_health_check", "run", outcome="ok", reversible=True)
    
    return json.dumps(report)  # Cron captures JSON for parsing


def check_disk_capacity() -> dict:
    """Check all datastores."""
    ssh = _get_ssh_pve()
    out, _, _ = ssh.run("df -h /var/lib/vz /mnt/datastore 2>/dev/null")
    
    # Parse: find any > 85%
    problems = []
    for line in out.split("\n")[1:]:
        if line.strip():
            parts = line.split()
            pct = int(parts[-2].rstrip("%"))
            mount = parts[-1]
            if pct >= 90:
                problems.append(f"{mount}: {pct}% (CRITICAL)")
            elif pct >= 85:
                problems.append(f"{mount}: {pct}% (WARN)")
    
    return {
        "status": "critical" if any("CRITICAL" in p for p in problems) else "ok" if not problems else "warn",
        "issues": problems,
        "check_time_sec": 2,
    }


def check_backup_health() -> dict:
    """Check last backup for each VM."""
    ssh = _get_ssh_pve()
    
    # Get all VMs
    vms = _get_all_vms(ssh)
    
    failed = []
    oldest_hours = 0
    
    for vm_id, vm_info in vms.items():
        # Find last backup for this VM
        out, _, _ = ssh.run(
            f"ls -lt /var/lib/vz/dump/ | grep 'qemu-{vm_id}' | head -1",
            check=False
        )
        
        if not out.strip():
            # No backup found
            if vm_info["tags"].get("backup") != "no":  # Should have backup
                failed.append(f"VM {vm_id} ({vm_info['name']}): NO BACKUP FOUND")
        else:
            # Check age
            age_hours = _get_file_age_hours(out)
            if age_hours > 24:
                failed.append(f"VM {vm_id}: backup {age_hours}h old")
            oldest_hours = max(oldest_hours, age_hours)
    
    prod_failed = any("prod" in f.lower() for f in failed)
    
    return {
        "status": "critical" if failed else "ok",
        "failed_count": len(failed),
        "prod_failed": prod_failed,
        "oldest_hours": oldest_hours,
        "issues": failed[:5],  # Top 5
    }


def check_pbs_health() -> dict:
    """Check PBS: GC status, disk usage, sync jobs."""
    ssh = _get_ssh_pbs()
    
    # GC status
    gc_out, _, _ = ssh.run(
        "tail -20 /var/log/proxmox-backup/tasks/archive | grep -i 'garbage'",
        check=False
    )
    gc_failed = "failed" in gc_out.lower() or "error" in gc_out.lower()
    
    # Disk usage
    disk_out, _, _ = ssh.run("df -h /mnt/datastore /mnt/hetzner 2>/dev/null")
    disk_fill_rate = _estimate_fill_rate(disk_out)  # Returns % per day
    
    # Replication status
    repl_out, _, _ = ssh.run(
        "grep -c 'error\\|ERROR' /var/log/proxmox-backup/tasks/sync 2>/dev/null",
        check=False
    )
    repl_errors = int(repl_out.strip() or "0")
    
    return {
        "status": "critical" if gc_failed else "warn" if disk_fill_rate > 20 else "ok",
        "gc_failed": gc_failed,
        "disk_fill_rate_percent_per_day": disk_fill_rate,
        "replication_errors": repl_errors,
    }


def check_critical_services() -> dict:
    """Check essential services are running."""
    ssh = _get_ssh_pve()
    
    critical = ["pveproxy", "pvedaemon", "pmgproxy"]
    failed = []
    
    for svc in critical:
        out, _, rc = ssh.run(f"systemctl is-active {svc}", check=False)
        if rc != 0:
            failed.append(svc)
    
    return {
        "status": "critical" if failed else "ok",
        "any_failed": bool(failed),
        "failed_services": failed,
    }


def format_ntfy_alert(report: dict) -> str:
    """Format JSON report into readable ntfy alert."""
    status = report["status"]
    emoji = {"critical": "🔴", "warning": "🟠", "healthy": "🟢"}[status]
    
    lines = [f"{emoji} Proxmox Daily Check — {status.upper()}"]
    
    for check_name, check_result in report["checks"].items():
        if check_result["status"] != "ok":
            if "issues" in check_result and check_result["issues"]:
                for issue in check_result["issues"][:2]:
                    lines.append(f"  • {check_name}: {issue}")
    
    return "\n".join(lines)
```

**Integration with cron:**
```bash
#!/bin/bash
# /usr/local/bin/proxmox-daily-check.sh

cd ~/.proxmox-agent

# Run health check (returns JSON)
output=$(python3 main.py --no-llm 2>&1)

# Extract status from audit log
status=$(grep "daily_health_check" .operations/audit.jsonl | tail -1 | jq -r '.status // "unknown"')

# Send alert via ntfy (only if critical/warning)
if [[ "$status" == "critical" ]] || [[ "$status" == "warning" ]]; then
    curl -d "$output" -H "Title: Proxmox Daily Check" -H "Priority: high" \
        $NTFY_URL
fi
```

**Benefit:** You wake up to a comprehensive health picture, not just "something's wrong."

---

## Improvement #2: Smart Approval Workflow in GUI (3 days)

**What you have now:**
```
User: "Fix my PBS GC issue"
  ↓
Agent: Shows dry-run
  ↓
User: Clicks "Apply"
  ↓
Agent: Executes
```

**Problem:** No context about risk. User has to decide based on description alone.

**Improvement: Risk-Aware Approval UI**

```javascript
// In gui/assistant.js

function showApprovalModal(operation, dryRun) {
  // Classify risk
  const risk = classifyRisk(operation);  // returns {level, reversible, impact, estimate}
  
  // Show detailed modal with:
  // 1. What will change (dry-run)
  // 2. Risk level (color-coded: 🟢 low / 🟡 medium / 🔴 high)
  // 3. Reversibility (can you undo? how long?)
  // 4. Rollback steps (if it goes wrong)
  // 5. Confidence score (agent's certainty: 95% sure this will work)
  
  const modal = document.createElement('div');
  modal.className = 'approval-modal';
  modal.innerHTML = `
    <div class="modal-content">
      <h2>Approve Operation</h2>
      
      <div class="risk-badge risk-${risk.level}">
        ${risk.level === 'low' ? '🟢' : risk.level === 'medium' ? '🟡' : '🔴'}
        ${risk.label}
      </div>
      
      <section>
        <h3>What Will Change</h3>
        <pre>${escapeHtml(dryRun)}</pre>
      </section>
      
      <section>
        <h3>Risk Assessment</h3>
        <table>
          <tr>
            <td>Reversible:</td>
            <td>${risk.reversible ? '✅ Yes' : '❌ No'} (${risk.reversible_time})</td>
          </tr>
          <tr>
            <td>Scope:</td>
            <td>${risk.impact}</td>
          </tr>
          <tr>
            <td>Confidence:</td>
            <td>${risk.confidence_percent}% sure this will work</td>
          </tr>
        </table>
      </section>
      
      <section>
        <h3>If This Goes Wrong</h3>
        <ol>
          ${risk.rollback_steps.map(s => `<li>${s}</li>`).join('')}
        </ol>
      </section>
      
      <div class="buttons">
        <button onclick="approveOperation('${operation}')">✅ Approve</button>
        <button onclick="dryRunOnly()">👁️ Dry-Run Only</button>
        <button onclick="cancelOperation()">❌ Cancel</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
}

function classifyRisk(operation) {
  const risks = {
    "pbs.fix.gc_permissions": {
      level: "low",
      label: "Low Risk: Config Change",
      reversible: true,
      reversible_time: "30 seconds",
      impact: "PBS only (does not affect Proxmox)",
      confidence_percent: 95,
      rollback_steps: [
        "cp /etc/proxmox-backup/datastore.cfg.bak /etc/proxmox-backup/datastore.cfg",
        "systemctl restart proxmox-backup"
      ]
    },
    "restart_service": {
      level: "low",
      label: "Low Risk: Service Restart",
      reversible: true,
      reversible_time: "Automatic (service restarts)",
      impact: "Service unavailable for ~5 seconds",
      confidence_percent: 98,
      rollback_steps: ["Service will auto-restart"]
    },
    "apply_patches": {
      level: "medium",
      label: "Medium Risk: Packages Updated",
      reversible: true,
      reversible_time: "5-10 minutes",
      impact: "Affects 1-3 guests",
      confidence_percent: 87,
      rollback_steps: [
        "apt-get install <package>=<old_version> (if version available)",
        "Restore from backup if major breakage"
      ]
    },
    "delete_vm": {
      level: "high",
      label: "HIGH RISK: Data Loss Possible",
      reversible: false,
      reversible_time: "N/A",
      impact: "Permanent deletion of VM and all data",
      confidence_percent: 50,
      rollback_steps: ["Restore from backup (if exists)"]
    },
  };
  
  return risks[operation] || {
    level: "unknown",
    label: "Unknown Risk",
    reversible: false,
    impact: "Unknown",
    confidence_percent: 0,
    rollback_steps: []
  };
}
```

**Result:** User sees risk **before** approving. Low-risk ops get approved faster because context is clear.

---

## Improvement #3: Audit Log Analysis & Weekly Insights (2 days)

**What you have now:**
```
.operations/audit.jsonl
├─ Line 1: {"timestamp": "...", "tool": "check_pbs", ...}
├─ Line 2: {"timestamp": "...", "tool": "get_inventory", ...}
└─ (Just appended, never analyzed)
```

**What you're missing:** Insights from patterns.

**Improvement: Weekly Learning Report**

```python
# New file: tools/analyze_audit.py

@tool(
    name="weekly_insights",
    description="Analyze audit logs from past 7 days — find patterns, suggest improvements",
    input_schema={"type": "object", "properties": {}, "required": []}
)
def weekly_insights() -> str:
    """
    Run weekly (Sunday night) to analyze patterns and suggest actions.
    """
    audit_logs = load_audit_logs(days=7)
    
    report = {}
    
    # Insight 1: Most used tools
    tool_counts = Counter(log["tool"] for log in audit_logs)
    report["most_used"] = tool_counts.most_common(5)
    # Result: [("check_pbs", 12), ("get_inventory", 8), ...]
    
    # Insight 2: Tool sequences (what do you do together?)
    sequences = find_sequences(audit_logs, window=5)  # Within 5 minutes
    report["sequences"] = sequences.most_common(3)
    # Result: [("check_pbs" -> "pbs_maintenance", 3 times), ...]
    # Action: "Create composite tool pbs_health_cycle"
    
    # Insight 3: Success/failure rates
    success_rates = {}
    for tool in tool_counts:
        passed = len([l for l in audit_logs if l["tool"] == tool and l["outcome"] == "ok"])
        total = len([l for l in audit_logs if l["tool"] == tool])
        success_rates[tool] = passed / total if total > 0 else 0
    
    # Flag low success rate (<80%)
    failing_tools = {t: r for t, r in success_rates.items() if r < 0.8}
    report["failing_tools"] = failing_tools
    # Action: "pbs_repair_tool succeeds 65% — investigate common failure modes"
    
    # Insight 4: When do problems happen?
    time_distribution = analyze_time_of_day(audit_logs)
    report["problem_times"] = [t for t, count in time_distribution if count > threshold]
    # Result: "Most failures between 3-4 AM, probably GC time"
    
    # Insight 5: What takes longest?
    slow_tools = {t: avg_time for t, avg_time in analyze_execution_time(audit_logs).items() 
                  if avg_time > 1000}  # >1 second
    report["performance"] = slow_tools
    # Action: "check_pbs takes 2.3s on average — can we cache results?"
    
    # Format as report
    formatted = format_insights_report(report)
    
    # Save for human review
    with open(".operations/insights-2026-06-03.md", "w") as f:
        f.write(formatted)
    
    audit.log("weekly_insights", "run", outcome="ok", reversible=True)
    
    return formatted


def format_insights_report(report: dict) -> str:
    """Format insights as readable Markdown."""
    md = "# Weekly Insights Report\n\n"
    
    md += "## 📊 Most Used Tools\n"
    for tool, count in report["most_used"]:
        md += f"- `{tool}`: used {count} times\n"
    
    md += "\n## 🔄 Common Sequences\n"
    for seq, count in report["sequences"]:
        from_tool, to_tool = seq
        md += f"- `{from_tool}` → `{to_tool}` ({count} times)\n"
        md += f"  💡 Suggestion: Create composite tool\n"
    
    md += "\n## ⚠️ Tools to Improve\n"
    if report["failing_tools"]:
        for tool, rate in report["failing_tools"].items():
            md += f"- `{tool}`: {rate*100:.0f}% success rate\n"
            md += f"  📍 Investigate common failure modes\n"
    else:
        md += "✅ All tools have >80% success rate\n"
    
    md += "\n## ⏰ Problem Patterns\n"
    if report["problem_times"]:
        for time_range in report["problem_times"]:
            md += f"- Most issues at {time_range}\n"
    
    md += "\n## ⚡ Performance\n"
    if report["performance"]:
        for tool, time_ms in report["performance"].items():
            md += f"- `{tool}`: {time_ms:.0f}ms (slow, consider optimization)\n"
    
    return md
```

**Integration with cron:**
```bash
# Run Sundays at 22:00 UTC
0 22 * * 0 cd ~/.proxmox-agent && python3 -c \
  "from tools.analyze_audit import weekly_insights; \
   report = weekly_insights(); \
   print(report)"
```

**Result:** You get actionable insights without asking. "Create composite tool", "Fix failing tool", "Optimize slow query."

---

## Improvement #4: Community Knowledge in the GUI (3 days)

**What you have now:**
When you ask a question, agent searches docs but not community.

**Improvement: Show Reddit/Forum Discussions in Context**

```python
# In tools/community_search.py

@tool(
    name="search_community_experience",
    description="Search Reddit/forums for people who had similar problems — what did they do?",
    input_schema={
        "type": "object",
        "properties": {
            "problem": {
                "type": "string",
                "description": "What's your issue? (e.g., 'PBS disk fills up')"
            },
            "show_solutions": {
                "type": "boolean",
                "description": "Show what worked for others?",
                "default": True
            }
        },
        "required": ["problem"],
    }
)
def search_community_experience(problem: str, show_solutions: bool = True) -> str:
    """
    Search r/Proxmox, Proxmox forums, Debian forums for similar issues.
    Return real discussions (not generic advice).
    """
    
    results = []
    
    # Search Reddit r/Proxmox
    reddit_posts = search_reddit(
        subreddit="Proxmox",
        query=problem,
        sort="new",
        limit=3
    )
    
    for post in reddit_posts:
        solution = extract_solution(post.comments)
        results.append({
            "source": "Reddit r/Proxmox",
            "title": post.title,
            "upvotes": post.score,
            "solution": solution,
            "url": f"https://reddit.com{post.permalink}"
        })
    
    # Search Proxmox forum
    forum_posts = search_forum(
        site="forum.proxmox.com",
        query=problem,
        limit=3
    )
    
    for post in forum_posts:
        results.append({
            "source": "Proxmox Forum",
            "title": post.title,
            "solution": post.accepted_answer,
            "url": post.url
        })
    
    # Format report
    report = "## What Others Did\n\n"
    for i, result in enumerate(results, 1):
        report += f"### {i}. {result['source']}\n"
        report += f"**{result['title']}** ({result.get('upvotes', '?')} upvotes)\n\n"
        report += f"**Solution:** {result['solution'][:200]}...\n\n"
        report += f"[Full discussion]({result['url']})\n\n"
    
    return report
```

**When to use:** Agent can offer this when you describe a problem.

```
You: "My PBS disk keeps filling up"

Agent: 
"I can help. Let me check your config, but first let me see 
what others experienced with this problem..."

[Shows 3 Reddit discussions where people solved disk fill]

"Here are the most common solutions:
1. Enable GC with atime-safety-check=false (7 upvotes)
2. Implement retention policies (12 upvotes)
3. Check replication target size (3 upvotes)"

Based on your setup, solution #1 looks best. Want me to apply it?"
```

**Benefit:** You get battle-tested solutions, not theoretical advice.

---

## Improvement #5: Feedback Collection in GUI (2 days)

**What you have now:** Agent works, but you don't rate features.

**Improvement: Rate Features, Help Agent Learn**

```javascript
// In gui/assistant.js - after tool execution

function showFeedbackPrompt(toolName, result) {
  const feedback = document.createElement('div');
  feedback.className = 'feedback-card';
  feedback.innerHTML = `
    <div>
      <p>Was this helpful?</p>
      <div class="rating">
        ${[1,2,3,4,5].map(star => `
          <button onclick="rateTool('${toolName}', ${star})" 
                  class="star" data-value="${star}">
            ${star <= 3 ? '⭐' : '✨'}
          </button>
        `).join('')}
      </div>
      <textarea placeholder="Any feedback?" 
                id="feedback-text-${toolName}"></textarea>
      <button onclick="submitFeedback('${toolName}')">Submit</button>
    </div>
  `;
  document.getElementById('results').appendChild(feedback);
}

function submitFeedback(toolName) {
  const rating = document.querySelector('[data-value].selected')?.dataset.value || 0;
  const comment = document.getElementById(`feedback-text-${toolName}`).value;
  
  fetch('/api/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      tool: toolName,
      rating: parseInt(rating),
      comment: comment,
      timestamp: new Date().toISOString()
    })
  });
}
```

```python
# In server.py

@app.post("/api/feedback")
async def submit_feedback(body: dict):
    """Collect user feedback on tools."""
    feedback = {
        "timestamp": datetime.utcnow().isoformat(),
        "tool": body.get("tool"),
        "rating": body.get("rating"),
        "comment": body.get("comment", ""),
    }
    
    # Append to feedback log
    with open(".operations/feedback.jsonl", "a") as f:
        f.write(json.dumps(feedback) + "\n")
    
    audit.log("feedback.submit", body.get("tool"), outcome="ok", reversible=False)
    
    return {"ok": True, "message": "Thank you for the feedback!"}
```

**What this enables:** The weekly insights report can now say:
- "pbs_repair_tool: 4.8/5 stars (users love it)"
- "security_audit: 2.1/5 stars (too verbose, improve output)"
- "weekly_insights: 4.5/5 stars (very useful, use weekly)"

---

## Summary: Pick 2-3 to Start

| Priority | Improvement | Effort | Impact | Payoff |
|----------|---|---|---|---|
| 1️⃣ High | Better daily health checks | 2 days | You wake to full picture, not just "critical" | Worth it |
| 2️⃣ High | Risk-aware approval UI | 3 days | Users approve faster (less overthinking) | Worth it |
| 3️⃣ Medium | Weekly audit insights | 2 days | Learn what tools matter + failures | Nice to have |
| 4️⃣ Medium | Community knowledge search | 3 days | Get battle-tested solutions | Very nice |
| 5️⃣ Low | Feedback collection | 2 days | Data for future improvements | Nice to have |

---

## My Recommendation

**Start here (this week):**

1. **Improvement #1** (Better health checks) — Most impact, used daily
2. **Improvement #2** (Risk-aware UI) — Makes approval faster + safer

**Then (next week):**

3. **Improvement #5** (Feedback collection) — Costs nothing, enables learning
4. **Improvement #3** (Weekly insights) — Set it and forget it, useful every Sunday

**Later (month 2):**

5. **Improvement #4** (Community search) — Nice to have, can search manually for now

---

## Implementation Path

**Week 1:**
```
Mon-Tue: Improvement #1 (daily health checks)
  ├─ Create daily_health_check.py
  ├─ Add checks: disk, backups, PBS, security, services
  ├─ Format ntfy alert
  └─ Test with cron

Wed-Thu: Improvement #2 (risk-aware UI)
  ├─ Add classifyRisk() to assistant.js
  ├─ Create approval modal
  ├─ Show dry-run + risk level + rollback steps
  └─ Test with a few operations

Fri: Testing + refinement
```

**Week 2:**
```
Mon-Tue: Improvement #5 (feedback collection)
  ├─ Add POST /api/feedback endpoint
  ├─ Add rating stars to GUI
  ├─ Save feedback to feedback.jsonl
  └─ Done

Wed-Thu: Improvement #3 (weekly insights)
  ├─ Create analyze_audit.py
  ├─ Extract patterns (sequences, success rates, timing)
  ├─ Generate insights report
  └─ Schedule with cron

Fri: Integration + testing
```

**Time total:** ~10-12 days, can parallelize with other work.

---

## TL;DR

You asked: "Option C + improve frameworks"

Here's what you can improve **without a daemon:**

1. **Better health checks** (daily) — Know what's wrong before you ask
2. **Risk-aware approvals** (interactive) — Approve faster with context
3. **Audit analysis** (weekly) — Learn from patterns
4. **Community insights** (on-demand) — Battle-tested solutions
5. **Feedback collection** (continuous) — Data for future learning

Pick #1 and #2 first (they're the most useful today). Do #3 next (passive learning). Save #4-5 for when you have time.

Want me to implement one of these?
