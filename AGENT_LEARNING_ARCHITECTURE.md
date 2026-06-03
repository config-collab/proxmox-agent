# Agent Learning Architecture

How your Proxmox agent learns, improves, and evolves over time while remaining safe and auditable.

---

## Three Types of Learning

### 1. **Observational Learning** (From Audit Logs)
Agent analyzes what it has done and what worked.

```
What it observes:
├─ Tool execution patterns ("check_pbs" called before "pbs_maintenance" 45x)
├─ User approval behavior ("always approve after dry-run")
├─ Success rates ("pbs_maintenance succeeds 92% of time")
├─ Time patterns ("GC failures happen at 03:30 UTC daily")
└─ Error patterns ("permission denied" always on /rclone-cache)

How it learns:
┌─────────────────────────────────────┐
│ audit.jsonl (append-only log)        │
│ [audit entries]                       │
└─────────────────────────────────────┘
         ↓ (Weekly analysis)
┌─────────────────────────────────────┐
│ Auto-generate insights:              │
│ - Most-used tool sequences           │
│ - Failure modes + root causes        │
│ - Opportunity for composite tools    │
│ - Performance bottlenecks            │
└─────────────────────────────────────┘
         ↓ (Suggest to human)
│ "Composite tool: pbs_health_cycle"  │
│ "Benefit: save 400 sec/week"        │
│ "Confidence: 95%"                    │
└─────────────────────────────────────┘

Agent does NOT change itself.
Human reviews suggestion, approves, implements.
```

### 2. **Community Learning** (From External Feedback)
Agent learns what people want from open sources.

```
Where feedback comes from:
├─ GitHub issues (feature requests with upvotes)
├─ Reddit discussions (pain points, wishlists)
├─ Community forums (patterns in questions)
├─ Direct feedback API (users rating features)
└─ User comments in code (TODO/FIXME)

How it learns:
┌─────────────────────────────────────┐
│ feedback.jsonl (user feedback)       │
│ github_issues.json (community votes) │
│ reddit_discussions.json (trends)     │
└─────────────────────────────────────┘
         ↓ (Weekly analysis)
┌─────────────────────────────────────┐
│ Auto-generate suggestions:           │
│ - Top 10 feature requests            │
│ - Problem domains with no solutions  │
│ - Common user questions              │
│ - What's trending in community       │
└─────────────────────────────────────┘
         ↓ (Suggest to product/human)
│ "Missing feature: auto-balance VMs" │
│ "Community interest: 7 upvotes"     │
│ "Estimated impact: 5 hours/week"    │
└─────────────────────────────────────┘

Agent does NOT decide on scope/priority.
Human product lead reviews, prioritizes, assigns.
```

### 3. **Behavioral Learning** (From User Interactions)
Agent learns how users interact with it.

```
What it observes:
├─ Which tools users call most often
├─ Which features get 5-star vs 1-star ratings
├─ Time between suggestion and user action
├─ Tool combinations that work well together
├─ Commands that fail and need rework
└─ Settings users change first/most often

How it learns:
┌─────────────────────────────────────┐
│ metrics.jsonl (feature performance)  │
│ {                                    │
│   "feature": "detect_disk_fill",    │
│   "execution_count": 45,             │
│   "success_rate": 0.92,              │
│   "user_rating_avg": 4.2,            │
│   "action_taken_rate": 0.87          │
│ }                                    │
└─────────────────────────────────────┘
         ↓ (Continuous analysis)
┌─────────────────────────────────────┐
│ Auto-generate insights:              │
│ - "This feature has high impact"    │
│ - "Users rarely act on this"        │
│ - "This combination saves time"     │
│ - "Interface needs improvement"     │
└─────────────────────────────────────┘

Agent learns but does NOT change itself.
Humans use insights to improve UX/features.
```

---

## Safe Learning Constraints

Your agent can learn OBSERVATIONALLY but not AUTONOMOUSLY. Here's why and how:

### ✅ What Agent CAN Do
```python
def analyze_audit_logs():
    """Agent can read and analyze its own history."""
    
    # ✅ ALLOWED: Read audit logs
    audit_data = read_audit_logs()
    
    # ✅ ALLOWED: Identify patterns
    tool_sequences = find_most_common_sequences(audit_data)
    # Result: [("check_pbs", "pbs_maintenance", 45), ...]
    
    # ✅ ALLOWED: Suggest improvements
    suggestion = {
        "type": "composite_tool",
        "reason": "Users call these 45 times in same session",
        "benefit": "Reduce 3 steps to 1"
    }
    
    # ✅ ALLOWED: Store suggestion for human review
    save_suggestion(suggestion)
    
    # ❌ NOT ALLOWED: Modify its own code
    # ❌ NOT ALLOWED: Add new tools without approval
    # ❌ NOT ALLOWED: Change parameters without testing
```

### Why This Design?

```
"Agent learns but humans decide" model:

✅ Safety: Agent cannot break itself
✅ Accountability: All changes are reviewed
✅ Auditability: Every improvement is a commit
✅ Reversibility: Bad changes can be rolled back
✅ Quality: Humans verify before deployment
✅ Transparency: Community can review decisions

vs.

❌ "Agent learns and modifies itself":
❌ Opaque: Where did this change come from?
❌ Risky: Agent could break itself
❌ Unauditable: No record of why change happened
❌ Uncontrollable: Can't easily roll back
❌ Trustworthiness: Who approved this?
```

---

## Learning Data Pipeline

### Data Collection (Continuous)

```
┌─────────────────────────────────────┐
│ Agent Operations (Real-time)         │
├─────────────────────────────────────┤
│ audit.log("tool_name", outcome)     │
│ metric("tool_name", exec_time_ms)   │
│ feedback("feature_id", rating)      │
└─────────────────────────────────────┘
         ↓
┌─────────────────────────────────────┐
│ Local Storage (Append-only)          │
├─────────────────────────────────────┤
│ .operations/audit.jsonl             │
│ .operations/metrics.jsonl           │
│ .operations/feedback.jsonl          │
└─────────────────────────────────────┘
```

### Analysis (Weekly Batch)

```python
def weekly_learning_analysis():
    """Run every Sunday at 00:00 UTC."""
    
    # Load all data from past week
    audits = load_jsonl(".operations/audit.jsonl")
    metrics = load_jsonl(".operations/metrics.jsonl")
    feedback = load_jsonl(".operations/feedback.jsonl")
    
    # Extract insights
    insights = {
        "tool_usage": analyze_tool_usage(audits),
        "success_rates": calculate_success_rates(metrics),
        "user_satisfaction": analyze_feedback(feedback),
        "common_patterns": find_patterns(audits),
        "failure_modes": extract_errors(audits),
    }
    
    # Generate report
    report = generate_learning_report(insights)
    
    # Save for human review
    save_report(report, "reports/learning_2026-06-03.md")
    
    # Notify operator
    notify_slack(
        "📊 Weekly learning report ready\n"
        f"Tool usage: {insights['tool_usage']}\n"
        f"Success rate: {insights['success_rates']}"
    )
    
    # Return suggestions
    return generate_suggestions(insights)
```

### Human Review (Weekly)

```
Operator opens: reports/learning_2026-06-03.md

Reads:
├─ Most-used tools
├─ Suggested improvements
├─ Problem areas
├─ Feature ideas
└─ Performance metrics

Decides:
├─ Which suggestions to implement
├─ Which to defer
├─ Which to close as "won't fix"
└─ What to tell community

Commits:
├─ Approves new feature
├─ Documents in CHANGELOG
├─ Links to discussion
└─ Pushes to main
```

---

## Example Learning Cycle

### Week 1: Observe

```json
[
  {"timestamp": "2026-06-01T14:32:00Z", "tool": "check_pbs", "outcome": "ok", "ms": 234},
  {"timestamp": "2026-06-01T14:32:15Z", "tool": "pbs_maintenance", "outcome": "ok", "ms": 1200},
  {"timestamp": "2026-06-01T14:32:35Z", "tool": "check_pbs", "outcome": "ok", "ms": 245},
  ...
  {"timestamp": "2026-06-08T14:00:00Z", "feature": "detect_disk_fill", "rating": 5, "comment": "Excellent!"}
]
```

### Week 2: Analyze

```markdown
## Learning Report: 2026-06-03

### Most Common Tool Sequences
1. check_pbs → pbs_maintenance → check_pbs (45 times)
   - Pattern: Diagnosis + action + verification
   - Opportunity: Create composite tool?

2. detect_disk_fill → cleanup_suggestion (38 times)
   - Pattern: Very high success rate (92%)
   - Opportunity: Auto-enable for all users?

### Performance Bottlenecks
- pbs_maintenance slow: avg 1.2s (needs optimization)
- network I/O is rate limiter for PBS queries

### User Satisfaction
- detect_disk_fill: 4.2★ (12 ratings)
- pbs_repair_tool: 4.8★ (8 ratings)
- legacy_admin_tool: 2.1★ (5 ratings) - needs rework

### Feature Ideas from Feedback
- [9 upvotes] Auto-balance resource allocation
- [7 upvotes] Cost tracking per guest
- [6 upvotes] Predict capacity limits
```

### Week 3: Implement

**Suggestion 1: Create Composite Tool**
```python
# Approved by operator, now implement

@tool(name="pbs_health_cycle", ...)
def pbs_health_cycle():
    """
    Run complete PBS health check cycle.
    Combines: check_pbs → pbs_maintenance → check_pbs
    
    Learning: These 3 tools were called together 45x/week
    Benefit: Reduce from 3 calls to 1, save 50 sec/week
    """
    result1 = check_pbs()
    result2 = pbs_maintenance(action="gc")
    result3 = check_pbs()
    
    return combine_results(result1, result2, result3)
```

**Suggestion 2: Optimize pbs_maintenance**
```python
# Performance issue identified
# Before: 1.2s avg
# After: Use caching + async I/O

@tool(name="pbs_maintenance", ...)
async def pbs_maintenance(action: str):
    """Now uses async SSH + connection pooling."""
    # See commit: "perf: parallelize PBS queries"
    pass
```

**Suggestion 3: Rework Low-Rated Feature**
```
legacy_admin_tool has 2.1★ rating
→ Scheduled for UX overhaul next sprint
→ Will split into smaller, clearer tools
```

---

## Exposing Learning to Users

### In-App Dashboard

```
┌─────────────────────────────────────────┐
│ 📊 Agent Learning Dashboard              │
├─────────────────────────────────────────┤
│                                          │
│ This Week's Improvements                 │
│ ├─ New feature: pbs_health_cycle        │
│ │  (from analyzing your workflow)        │
│ ├─ Optimization: PBS queries 40% faster  │
│ │  (from performance metrics)            │
│ └─ [You rated features 48 times]         │
│    (helps prioritize our work)           │
│                                          │
│ Community Impact                         │
│ ├─ Top request: Cost tracking (7 upvotes)
│ ├─ We're working on: Auto-balance (3mo)  │
│ └─ [Vote on features you want]           │
│                                          │
│ Your Agent Knows                         │
│ ├─ 12 unique tools you use regularly     │
│ ├─ You prefer dry-run before changes     │
│ └─ Downtime cost: ~$45/incident          │
│                                          │
└─────────────────────────────────────────┘
```

### Weekly Newsletter

```markdown
📬 Agent Learning Report — Week of Jun 3, 2026

## What Learned

- Your most common task: PBS health checks (45x/week)
- New composite tool created: pbs_health_cycle (saves 400s/week)
- Performance: Cut PBS queries from 1.2s to 0.7s (40% faster)

## Community Feedback

- Top request: Auto-balance VMs (9 upvotes, 6 comments)
- Trending: Cost tracking per guest
- Latest: 4 new feature requests this week

## Your Feedback Helped

Your 48 feature ratings this week shaped our priorities:
- detect_disk_fill: 4.2★ — keeping, expanding
- legacy_admin_tool: 2.1★ — scheduled for redesign

## Next Week

We're implementing:
- Auto-balance VM resources (from community request)
- Cost per guest tracking (beta)
- Optimize network queries further
```

---

## Community Contribution Pipeline

### How External Devs Contribute

```
1. SEE OPPORTUNITY
   "I notice the agent should detect X"
   
2. PROPOSE (GitHub Discussion)
   "Here's how I'd implement it"
   "5 users have asked for this"
   
3. PROTOTYPE (PR with [EXPERIMENTAL] tag)
   "I built a prototype, here's the code"
   "Test it with: BETA_NEW_FEATURE=1"
   
4. COMMUNITY VALIDATION
   "3+ users test in beta"
   "Feedback: works great! One issue..."
   
5. PRODUCTION (Merged to main)
   "After 2 weeks, moving to default"
   "Thanks for the contribution!"
```

### Contribution Guidelines

```markdown
# Contributing Features

## Process

1. **Propose** in [GitHub Discussions](...)
   - Describe the problem
   - Link existing issues
   - Show interest (upvotes/comments)

2. **Prototype** (fork + feature branch)
   - Implement as @tool(experimental=True)
   - Write tests
   - Open PR with [EXPERIMENTAL] tag

3. **Beta Testing** (2-4 weeks)
   - Tag with BETA_YOUR_FEATURE env var
   - Collect user feedback
   - Fix issues

4. **Stabilize** (merge to main)
   - Remove experimental flag
   - Update documentation
   - Share in release notes

## Example

```python
# Your PR
@tool(name="auto_balance_vms", experimental=True)
def auto_balance_vms():
    """Distribute VM resources evenly across hosts."""
    pass
```

Feedback from community:
- "Works great!" (5 👍)
- "One edge case: clustered VMs" (1 issue)

After fix:
- Merged! Your feature is now live
- Listed in CHANGELOG
- Your name in CONTRIBUTORS
```

---

## Metrics: Is the Agent Getting Smarter?

### Measure Learning

```
Per week:
├─ New tools added (from suggestions): target 1-2
├─ Tool improvements (from feedback): target 2-3
├─ Performance gains (from metrics): track % improvement
├─ User satisfaction (avg rating): target >4.0★
└─ Community engagement (issues/PRs): growing?

Per quarter:
├─ Major features shipped (from community votes)
├─ Reduction in user manual tasks (audit analysis)
├─ Cost savings (from agent suggestions)
└─ Community size (GitHub stars, Reddit followers)
```

### Success Indicators

```
The agent is learning if:
✅ Most-used tool combinations become composite tools
✅ Failure modes are identified and fixed (not just observed)
✅ Community requests turn into features within 4 weeks
✅ User satisfaction stays >4.0★ across all tools
✅ New contributors are adding features
✅ Tool execution time keeps improving
✅ Outages are prevented by agent detection

The learning loop is broken if:
❌ Suggestions are collected but never implemented
❌ Community requests accumulate in backlog forever
❌ Low-rated tools don't get improved
❌ Performance keeps degrading
❌ No new external contributors
```

---

## Summary: The Learning Virtuous Cycle

```
Your Operations
    ↓ (Agent observes)
Audit Logs
    ↓ (Weekly analysis)
Insights + Suggestions
    ↓ (Human review)
Approved Improvements
    ↓ (Implemented)
Better Agent
    ↓ (Handles more)
Fewer Manual Tasks
    ↓ (More time for)
Feature Requests
    ↓ (Community votes)
Prioritized Roadmap
    ↓ (External contributions)
Community Involvement
    ↓ (More users)
Your Operations [← Loop repeats]
```

This is how an agent learns safely:
- **Observe** everything (audit logs, feedback, metrics)
- **Analyze** patterns (find opportunities)
- **Suggest** improvements (to humans)
- **Implement** when approved (by humans)
- **Measure** impact (did it help?)
- **Repeat** (rinse and repeat)

No autonomous self-modification. Just intelligent observation + human judgment.
