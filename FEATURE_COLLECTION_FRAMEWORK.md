# Feature Collection & Learning Framework

How to systematically collect, validate, and integrate new agent capabilities from users, operations, and community.

---

## The Core Loop

```
Collect → Validate → Test → Integrate → Monitor → Iterate
  ↑                                                    ↓
  └────────────────────────────────────────────────────
```

---

## 1. Collection Sources

### A. Operations-Driven (Your Infrastructure)
**Where:** From actual maintenance work you do on your Proxmox

**How to capture:**
```markdown
## Feature Request Template (In CLAUDE.md or operations log)

When you find yourself doing this manually:
- Running the same SSH commands repeatedly
- Diagnosing a pattern (e.g., "check disk usage on all VMs")
- Making the same decision (e.g., "is it safe to patch?")
- Following a checklist each time

→ Log it in `.operations/pending_features.json`:
{
  "id": "feature-001",
  "date": "2026-06-03",
  "title": "Auto-detect and fix disk fill alerts",
  "frequency": "weekly",
  "manual_steps": [
    "SSH to each VM",
    "Run df -h",
    "Check if >80%",
    "Suggest cleanup"
  ],
  "estimated_time_savings": "30 min/week",
  "owner": "user",
  "status": "pending_validation"
}
```

**Sources to watch:**
- Audit logs (what do you repeat?)
- Operations runbooks (convert to automation)
- Time spent on manual tasks (biggest ROI)
- Pain points in backups, patching, security

### B. Community-Driven (GitHub Issues / Discussions)
**Where:** Other Proxmox users, forums, GitHub issues

**How to capture:**
```
GitHub Issues labeled: feature-request
├─ Upvote = interest signal
├─ Comments = Use cases
└─ Code examples = Validation

Proxmox Forums
├─ Watch for: "I wish the agent could..."
└─ Convert to issues with community consensus

Reddit (r/Proxmox)
├─ Search: "agent should"
└─ Link to issues for discussion
```

**Lightweight tracking:**
```markdown
## Community Feature Requests
- [ ] Issue #42: "Detect and alert on VM CPU pinning mismatches" (3 👍)
- [ ] Issue #47: "Auto-balance resource allocation across cluster" (7 👍)
- [ ] Issue #51: "Generate capacity planning reports" (2 👍)
- [ ] Reddit discussion: "Real-time cost tracking for guests" (12 comments)
```

### C. Operator Feedback (Direct)
**Where:** Chat, email, voice from your team or users

**How to capture:**
```bash
# Create feedback intake form / script
cat > .operations/submit_feedback.sh << 'EOF'
#!/bin/bash
# Submit feature request or bug report

echo "=== Proxmox Agent Feedback ==="
read -p "Title: " title
read -p "Category (feature/bug/improvement): " category
read -p "Description: " description
read -p "Your name/email: " author

# Auto-append to feedback log
cat >> .operations/feedback.jsonl << JSON_EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "title": "$title",
  "category": "$category",
  "description": "$description",
  "author": "$author",
  "status": "new"
}
JSON_EOF

echo "✓ Feedback submitted. Thank you!"
EOF
chmod +x .operations/submit_feedback.sh
```

---

## 2. Feature Validation Pipeline

### Gate 1: Viability Check
```
Can the agent actually do this?
├─ ✅ Read-only? (Always possible)
├─ ✅ Reversible? (Safe to add)
├─ ✅ Requires new data source? (Cost/benefit)
├─ ✅ Depends on external API? (Reliability)
└─ ❌ Impossible? (Block)
```

### Gate 2: Impact Assessment
```
How much value does this add?
├─ Time savings: X minutes per week
├─ Risk reduction: Prevents what problems?
├─ Scope: % of users affected
├─ Complexity: Lines of code needed
└─ Priority score: (savings × scope) / complexity
```

### Gate 3: Threat Model
```
Is this safe?
├─ Can it cause data loss? (No? Good.)
├─ Can it be abused? (Design around it)
├─ Does it leak secrets? (Block sensitive data)
├─ Can it cascade failures? (Require approval)
└─ Risk level: Read-only / Reversible / Irreversible
```

**Example evaluation:**

```markdown
## Feature: Detect and Fix Disk Fill Automatically

| Gate | Status | Notes |
|------|--------|-------|
| **Viability** | ✅ YES | Can read disk usage, suggest cleanup, ask user |
| **Value** | ✅ HIGH | Prevents 2 production incidents/year, 30min/week |
| **Safety** | ⚠️ MEDIUM | Risk: delete wrong files. Mitigation: dry-run only |
| **Complexity** | ✅ LOW | ~200 lines, uses existing tools |
| **Priority** | 92/100 | (60 × 0.8) / 0.5 |
| **Decision** | ✅ APPROVE | Proceed to development |
```

---

## 3. Development Workflow

### Phase 1: Prototype (Local)
```python
# In tools/new_feature_tool.py (experimental branch)

@tool(
    name="detect_disk_fill",
    description="Find guests approaching disk capacity, suggest cleanup.",
    input_schema={...},
    experimental=True,  # Metadata: not in production yet
    feature_id="feature-001",
)
def detect_disk_fill():
    """Prototype implementation."""
    # MVP: Minimal viable feature
    # Focus on core logic, not edge cases
    pass
```

### Phase 2: Testing (Sandbox)
```bash
# Run on non-production data only
pytest tests/feature_detect_disk_fill.py -v

# Test matrix:
├─ Happy path (disks at 50%, 75%, 90%)
├─ Edge cases (100%, 0%, errors)
├─ Integration (with other tools)
└─ Safety (doesn't delete anything)
```

### Phase 3: Beta (Real Data, Ask First)
```python
# In server.py, tag beta features

BETA_FEATURES = {
    "detect_disk_fill": {
        "enabled": os.environ.get("BETA_DETECT_DISK_FILL") == "1",
        "version": "0.1",
        "feedback_url": "github.com/.../issues/42"
    }
}

# In tool output:
"ℹ️ BETA: This feature is experimental. "
"Your feedback helps us improve: "
"https://github.com/.../issues/42"
```

### Phase 4: Stabilization (Gradual Rollout)
```
Week 1: 10% of users (explicit opt-in)
Week 2: 50% of users (mentioned in docs)
Week 3: 100% of users (default, can opt-out)
```

---

## 4. Feedback Loop Integration

### Collect Performance Data
```python
# In every tool execution
class FeatureMetric:
    feature_id: str          # "feature-001"
    execution_time_ms: int   # How fast?
    success: bool           # Did it work?
    user_approved: bool     # User liked it?
    action_taken: bool      # User acted on suggestion?
    user_feedback: str      # Text feedback (optional)
    
# Example:
audit.metric(
    feature_id="detect_disk_fill",
    execution_time_ms=234,
    success=True,
    user_feedback="Caught a disk fill 3 days early, saved us!"
)
```

### Dashboard for Operators
```markdown
## Feature Adoption & Feedback

| Feature | Users | Success | Avg Time | Feedback |
|---------|-------|---------|----------|----------|
| detect_disk_fill | 12 | 85% | 234ms | 👍 "Great!" (3) |
| pbs_repair_tool | 8 | 92% | 450ms | 👍👍 (5) |
| auto_patch | 5 | 78% | 3200ms | ⚠️ "Too slow" (1) |
| cost_tracking | 2 | 100% | 150ms | 👍 (1) |

[+] Stabilized (>90% success, >10 users)
[~] In beta (80-90% success, <10 users)
[-] Struggling (<80% success, should rework)
```

---

## 5. Learning Mechanisms

### A. Observational Learning (From Audit Logs)
```python
# The agent can analyze its own audit trail

def learn_from_operations():
    """Extract patterns from what was actually useful."""
    
    # Query: "What were the most-used tool combinations?"
    # Result: Users often run (check_pbs → pbs_maintenance → check_pbs)
    # Learning: Create composite tool "pbs_health_cycle"
    
    # Query: "What features had highest approval rate?"
    # Result: Diagnose-only tools = 98% approval, write tools = 60%
    # Learning: Favor read-only + suggest patterns
    
    # Query: "What operations were rejected most?"
    # Result: "apply changes" always rejected without dry-run
    # Learning: Add dry-run to all write operations (learned requirement)
```

### B. User Feedback Analysis (NLP)
```python
def extract_feature_ideas_from_feedback():
    """Parse user comments for patterns."""
    
    feedback = [
        "I wish it would automatically...",
        "It should detect when...",
        "Can it also fix...",
        "This is slow, maybe...",
    ]
    
    # Extract suggestions:
    ├─ "automatically" → Autonomy request
    ├─ "detect when" → New diagnostic
    ├─ "also fix" → Expand existing tool
    └─ "slow, maybe" → Performance issue
```

### C. Community Intelligence (GitHub + Reddit)
```bash
# Automated scraping (with rate limits)
# Run weekly to find trends

curl -s "https://api.github.com/repos/config-collab/proxmox-agent/issues" \
  | jq '.[] | select(.labels[].name == "feature-request") | .title'

# Analyze:
# - Which feature requests have most upvotes?
# - What do multiple people ask for?
# - What problems repeat?
```

---

## 6. Structured Feature Tracking

### Create `.operations/features.db` (JSON format)
```json
{
  "features": [
    {
      "id": "feature-001",
      "title": "Detect and fix disk fill",
      "status": "stable",
      "created": "2026-05-20",
      "stabilized": "2026-06-10",
      "sources": ["operations", "github-issue-42"],
      "metrics": {
        "time_saved_per_week_minutes": 30,
        "success_rate": 0.92,
        "user_count": 12,
        "feedback_score": 4.2
      },
      "next_iteration": "Add automatic cleanup suggestions"
    },
    {
      "id": "feature-002",
      "title": "Real-time cost tracking",
      "status": "beta",
      "created": "2026-06-01",
      "sources": ["reddit", "community-request"],
      "metrics": {
        "user_count": 2,
        "success_rate": 1.0,
        "feedback_score": 5.0
      },
      "blockers": ["Need pricing API integration"]
    }
  ]
}
```

### Query Script (Analyze Features)
```bash
#!/bin/bash
# List features by adoption rate

jq '.features | sort_by(-.metrics.user_count) | .[] | 
  "\(.id): \(.title) - \(.metrics.user_count) users, \(.metrics.success_rate*100|floor)% success"' \
  .operations/features.db
```

---

## 7. Community Contribution Model

### For External Contributors
```markdown
# Contributing New Features

## 1. Propose (GitHub Discussion)
- Describe the problem you're solving
- Show manual steps you currently do
- Estimate time savings
- Link to similar issues

## 2. Prototype (Fork + PR)
- Create feature branch
- Implement as experimental tool
- Add tests
- Tag PR with [BETA]

## 3. Validate (Community Testing)
- 3+ users test in beta
- Collect feedback via GitHub
- Address issues

## 4. Stabilize (Merge to main)
- Gate behind BETA_FEATURES env var
- Add documentation
- Monitor metrics for 2 weeks

## 5. Promote (Default Enable)
- Remove beta flag
- Include in release notes
- Track long-term adoption
```

---

## 8. The Agent Learning Loop

### Can Your Agent Actually Learn?

**Current State:**
- ✅ Can read its own audit logs
- ✅ Can identify patterns in usage
- ✅ Can suggest new tools based on frequency
- ❌ Cannot modify its own code (would be risky)

**Safe Learning Model:**
```python
def suggest_new_features():
    """Agent analyzes audit logs and suggests improvements."""
    
    # Analyze: What tools are used together most?
    combos = analyze_tool_sequences(audit_logs)
    # Result: [("check_pbs", "pbs_maintenance", 45 times)]
    
    # Suggest: Create a composite tool
    suggestion = {
        "type": "composite_tool",
        "name": "pbs_health_cycle",
        "tools": ["check_pbs", "pbs_maintenance"],
        "benefit": "Reduce 3 steps to 1, save 50 sec/week × 8 users = 400 sec/week",
        "confidence": 0.95
    }
    
    # Return to human for approval
    return suggestion
```

### What the Agent Can Infer (But Not Change)
```
1. "Users never approve fast restarts without dry-runs"
   → Inference: Always show dry-run first

2. "When GC fails, 100% of cases are permission errors"
   → Inference: Check permissions before other diagnostics

3. "Email config is always first thing users set up"
   → Inference: Move email setup to initial setup flow

4. "pbs_repair_tool gets 5x more usage than individual tools"
   → Inference: Composite tools are valuable

→ Agent can SUGGEST these changes to humans
→ Humans APPROVE and merge
→ Agent benefits from the feedback loop
```

---

## 9. Implementation: Feedback Collection System

### Add to Server
```python
# In server.py

@app.post("/api/feedback")
async def submit_feedback(body: dict):
    """
    Collect user feedback on features.
    
    {
        "feature_id": "detect_disk_fill",
        "rating": 5,
        "comment": "This saved us from a disk fill!",
        "helpful": true
    }
    """
    feedback = {
        "timestamp": datetime.utcnow().isoformat(),
        **body
    }
    
    # Append to feedback log
    with open(".operations/feedback.jsonl", "a") as f:
        f.write(json.dumps(feedback) + "\n")
    
    audit.log("feedback.submit", body.get("feature_id", "unknown"),
              outcome="ok", reversible=False)
    
    return {"ok": True}
```

### UI Button (In GUI)
```javascript
// In gui/assistant.js

function submitFeedback(featureId, rating) {
  fetch('/api/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      feature_id: featureId,
      rating: rating,  // 1-5 stars
      comment: prompt('Any comments?') || '',
      helpful: rating >= 4
    })
  }).then(r => r.json())
    .then(() => alert('✓ Feedback sent. Thank you!'));
}
```

---

## 10. Release Process with Community Input

```
Main Branch (Stable)
    ↑
    │ (Feature passes 2 weeks @ 90% success)
    │
Beta Release (Community Testing)
    ↑
    │ (Feature in beta environment, 3+ users, feedback)
    │
Experimental Branch (Dev Feature)
    ↑
    │ (Suggested by users, implemented locally)
    │
Community Suggestions
├─ GitHub Issues
├─ Reddit Discussions  
├─ Operator Feedback
└─ Audit Log Analysis
```

---

## Quick Start: Implement This Today

### Step 1: Create Feature Tracking
```bash
mkdir -p .operations
cat > .operations/features.db << 'EOF'
{"features": []}
EOF

cat > .operations/feedback.jsonl << 'EOF'
EOF
```

### Step 2: Add Feedback API (10 min)
In `server.py`, add the `/api/feedback` endpoint above.

### Step 3: Tag Experimental Features
```python
# In tools/your_new_tool.py

@tool(
    name="new_feature",
    description="...",
    experimental=True,
    feature_id="feature-002"
)
def new_feature():
    pass
```

### Step 4: Monitor Adoption
```bash
# Weekly review script
jq '.features | map(select(.status == "beta")) | 
  .[] | "\(.title): \(.metrics.user_count) users"' \
  .operations/features.db
```

---

## Summary

| Source | How to Capture | Frequency | Value |
|--------|----------------|-----------|-------|
| **Operations** | Audit logs + time tracking | Ongoing | Highest (real pain) |
| **Community** | GitHub issues, Reddit, forums | Weekly | High (validated) |
| **Agent Logs** | Analyze usage patterns | Weekly | Medium (inferred) |
| **User Feedback** | Inline rating system | Ongoing | High (direct) |

**The Loop:**
```
Operations Pain
    ↓ (Capture)
Feature Idea
    ↓ (Validate & Prototype)
Experimental Tool
    ↓ (Test with users)
Beta Release
    ↓ (Collect feedback)
Stable Feature
    ↓ (Monitor adoption)
Operational Insight
    ↓ (Next iteration)
Better Tool
```

This creates a **self-improving system** where your agent gets better each week based on real usage patterns.
