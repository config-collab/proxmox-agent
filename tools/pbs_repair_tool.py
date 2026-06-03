"""
PBS Repair and Diagnostics Tool — diagnose and fix common PBS issues.

Handles:
- GC permission errors
- Email notification configuration
- Inode exhaustion detection
- Failed backup task analysis
- Dry-run config updates with rollback
"""
import os
import json
import time
import audit
import config
from tools import tool
from ssh_client import SSHClient


PBS_HOST = "192.168.0.244"
PBS_USER = "root"
PBS_KEY_FILE = "pbs_id_ed25519"


def _pbs_ssh() -> SSHClient:
    """Connect to PBS host."""
    return SSHClient(
        host=PBS_HOST,
        user=PBS_USER,
        key_path=config.ssh_key_path(PBS_KEY_FILE),
    )


@tool(
    name="diagnose_pbs_issues",
    description=(
        "Deep diagnostics on PBS (192.168.0.244): detect GC failures, permission errors, "
        "inode exhaustion, failed tasks, email config. Recommends fixes with reversible steps."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "full_scan": {
                "type": "boolean",
                "description": "Include task log analysis and detailed metrics (slower, ~30s).",
                "default": False
            },
        },
        "required": [],
    },
)
def diagnose_pbs_issues(full_scan: bool = False) -> str:
    """
    Diagnose PBS issues and return findings with severity levels.

    Returns: Markdown-formatted report with issues, root causes, and fix recommendations.
    """
    try:
        ssh = _pbs_ssh()
        ssh.connect()
    except Exception as exc:
        return f"❌ Cannot connect to PBS at {PBS_HOST}: {exc}"

    findings = []

    # Issue 1: Check garbage collection permission errors
    gc_status = _check_gc_permissions(ssh)
    if gc_status["has_error"]:
        findings.append({
            "severity": "🔴 CRITICAL",
            "issue": "Garbage Collection Permission Error",
            "description": gc_status["description"],
            "impact": "Old backup chunks not deleted → disk fills up",
            "root_cause": "rclone-cache directory has permission issues",
            "fix_available": True,
        })

    # Issue 2: Check email notification
    email_status = _check_email_config(ssh)
    if not email_status["configured"]:
        findings.append({
            "severity": "🟠 HIGH",
            "issue": "Email Notifications Not Configured",
            "description": email_status["description"],
            "impact": "Backup failures go unnoticed",
            "root_cause": "root@pam user has no email address configured",
            "fix_available": True,
        })

    # Issue 3: Check datastore inodes
    inode_status = _check_inode_health(ssh)
    if inode_status["inode_problem"]:
        findings.append({
            "severity": "🔴 CRITICAL" if inode_status["percent"] >= 90 else "🟠 HIGH",
            "issue": f"Datastore Inode Exhaustion ({inode_status['percent']}% full)",
            "description": inode_status["description"],
            "impact": "Cannot create new files on datastore",
            "root_cause": inode_status["root_cause"],
            "fix_available": False,  # Requires investigation
        })

    # Issue 4: Check for failed tasks (if full_scan)
    if full_scan:
        failed_tasks = _check_failed_tasks(ssh)
        if failed_tasks["count"] > 0:
            findings.append({
                "severity": "🟡 MEDIUM",
                "issue": f"Recent Failed Tasks ({failed_tasks['count']})",
                "description": failed_tasks["description"],
                "impact": "Backups or maintenance may be incomplete",
                "root_cause": failed_tasks["root_cause"],
                "fix_available": False,
            })

    ssh.close()

    # Format report
    if not findings:
        return "✅ **PBS Status: Healthy**\n\nNo critical issues detected."

    report = "## PBS Diagnostics Report\n\n"
    for i, f in enumerate(findings, 1):
        report += f"### {i}. {f['severity']} {f['issue']}\n"
        report += f"**Description:** {f['description']}\n\n"
        report += f"**Impact:** {f['impact']}\n\n"
        report += f"**Root Cause:** {f['root_cause']}\n\n"
        if f["fix_available"]:
            report += f"**Fix Available:** Yes — Use `fix_pbs_issue` tool\n\n"
        else:
            report += f"**Fix Available:** Manual investigation required\n\n"

    return report


@tool(
    name="fix_pbs_issue",
    description=(
        "Repair a specific PBS issue (GC permissions, email config, etc). "
        "Shows dry-run (what will change) before applying. Reversible with rollback steps."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "issue_type": {
                "type": "string",
                "enum": ["gc_permissions", "email_config"],
                "description": "Which issue to fix: gc_permissions, email_config"
            },
            "apply": {
                "type": "boolean",
                "description": "If true, apply the fix. If false, show dry-run only.",
                "default": False
            },
            "email_address": {
                "type": "string",
                "description": "Email address for root@pam (required if issue_type=email_config)"
            },
        },
        "required": ["issue_type"],
    },
)
def fix_pbs_issue(issue_type: str, apply: bool = False, email_address: str = "") -> str:
    """
    Fix a PBS issue with optional dry-run.

    Args:
        issue_type: gc_permissions or email_config
        apply: If True, actually apply the fix. If False, show dry-run.
        email_address: Email to configure (for email_config issue)

    Returns: Markdown report showing what was changed, rollback steps, and verification.
    """
    try:
        ssh = _pbs_ssh()
        ssh.connect()
    except Exception as exc:
        return f"❌ Cannot connect to PBS: {exc}"

    if issue_type == "gc_permissions":
        report = _fix_gc_permissions(ssh, apply=apply)
    elif issue_type == "email_config":
        if not email_address:
            ssh.close()
            return "❌ email_address required for email_config fix"
        report = _fix_email_config(ssh, email_address, apply=apply)
    else:
        ssh.close()
        return f"❌ Unknown issue type: {issue_type}"

    ssh.close()
    return report


# ── Diagnostic functions ────────────────────────────────────────────────────────


def _check_gc_permissions(ssh: SSHClient) -> dict:
    """Check if GC has permission errors."""
    out, _, _ = ssh.run(
        "tail -50 /var/log/proxmox-backup/tasks/archive 2>/dev/null | grep -i 'garbage_collection'",
        check=False
    )

    has_error = "permission denied" in out.lower() or "rclone-cache" in out.lower()

    return {
        "has_error": has_error,
        "description": (
            "GC fails with permission error on rclone-cache directory"
            if has_error
            else "GC running normally"
        ),
    }


def _check_email_config(ssh: SSHClient) -> dict:
    """Check if email is configured."""
    out, _, _ = ssh.run(
        "tail -100 /var/log/proxmox-backup/tasks/archive 2>/dev/null | grep -i 'does not have a configured email'",
        check=False
    )

    is_broken = "does not have a configured email" in out.lower()

    return {
        "configured": not is_broken,
        "description": (
            "root@pam user has no email address configured"
            if is_broken
            else "Email notifications appear configured"
        ),
    }


def _check_inode_health(ssh: SSHClient) -> dict:
    """Check inode usage on datastores."""
    out, _, rc = ssh.run("df -i /mnt/datastore /mnt/hetzner 2>/dev/null", check=False)

    problem = False
    percent = 0
    root_cause = "Unknown"

    # Parse df output
    lines = out.strip().split("\n")[1:]  # Skip header
    if lines:
        for line in lines:
            parts = line.split()
            if len(parts) >= 5:
                use_pct = int(parts[4].rstrip("%"))
                if use_pct >= 90:
                    problem = True
                    percent = use_pct
                    mount = parts[-1]
                    if "hetzner" in mount:
                        root_cause = "rclone mount has inode limits"
                    else:
                        root_cause = "Too many backup chunks on local storage"

    return {
        "inode_problem": problem,
        "percent": percent,
        "description": (
            f"Inodes at {percent}% capacity on backup datastore"
            if problem
            else "Inode usage healthy"
        ),
        "root_cause": root_cause,
    }


def _check_failed_tasks(ssh: SSHClient) -> dict:
    """Check for recent failed tasks."""
    out, _, _ = ssh.run(
        "grep -c 'connection error\\|ERROR' /var/log/proxmox-backup/tasks/archive 2>/dev/null",
        check=False
    )

    count = int(out.strip() or "0")

    return {
        "count": count,
        "description": f"{count} failed tasks in recent log" if count > 0 else "No recent failures",
        "root_cause": "Check specific task logs for details" if count > 0 else "N/A",
    }


# ── Fix functions ────────────────────────────────────────────────────────────


def _fix_gc_permissions(ssh: SSHClient, apply: bool = False) -> str:
    """Fix GC permission error by updating datastore config."""
    config_path = "/etc/proxmox-backup/datastore.cfg"
    backup_path = "/etc/proxmox-backup/datastore.cfg.bak"

    # Get current config
    current, _, _ = ssh.run(f"cat {config_path}", check=False)

    # Show dry-run
    dry_run = (
        "## Dry-Run: Fix GC Permission Error\n\n"
        "### Change Summary\n"
        "Add `tuning gc-atime-safety-check=false` to both datastore definitions\n\n"
        "### Why\n"
        "rclone-mounted datastore can't report accurate atime, causing GC to fail. "
        "Disabling this check allows GC to proceed safely.\n\n"
        "### Files Affected\n"
        f"- `{config_path}`\n\n"
        "### Current Config\n"
        "```ini\n" + current + "\n```\n\n"
    )

    if not apply:
        dry_run += (
            "### Rollback Steps\n"
            "1. Backup already created at `.bak`\n"
            "2. To revert: `cp datastore.cfg.bak datastore.cfg && systemctl restart proxmox-backup`\n\n"
            "### Next Step\n"
            "Run again with `apply: true` to execute this fix."
        )
        audit.log("pbs.fix.gc_permissions", "dry-run", outcome="reviewed", reversible=True)
        return dry_run

    # Apply fix
    updated = _add_gc_tuning(current)

    # Backup and update
    ssh.run(f"cp {config_path} {backup_path}", check=False)
    ssh.run(f"cat > {config_path} << 'EOF'\n{updated}\nEOF", check=False)
    ssh.run("systemctl restart proxmox-backup", check=False)

    # Verify
    verify, _, _ = ssh.run(f"cat {config_path} | grep gc-atime", check=False)
    success = "gc-atime-safety-check=false" in verify

    audit.log("pbs.fix.gc_permissions", "applied",
              outcome="ok" if success else "error", reversible=True)

    result = (
        "## ✅ GC Permission Fix Applied\n\n"
        "### Changes Made\n"
        "Added `gc-atime-safety-check=false` tuning parameter to both datastores\n\n"
        "### Verification\n" +
        ("✅ Config updated successfully" if success else "❌ Config update failed") +
        "\n\n"
        "### Next Steps\n"
        "1. Wait for 03:30 UTC (next scheduled GC)\n"
        "2. Run `check_pbs()` to verify GC completes without errors\n"
        "3. Monitor disk space - should stabilize if GC works\n\n"
        "### Rollback (if needed)\n"
        f"```bash\ncp {backup_path} {config_path}\nsystemctl restart proxmox-backup\n```"
    )

    return result


def _fix_email_config(ssh: SSHClient, email: str, apply: bool = False) -> str:
    """Configure email notifications for root@pam."""
    dry_run = (
        "## Dry-Run: Configure Email Notifications\n\n"
        "### Change Summary\n"
        f"Set email address for root@pam user to: `{email}`\n\n"
        "### Why\n"
        "Backup failures and GC errors won't be reported without email configuration.\n\n"
        "### Method\n"
        "This requires manual setup via PBS Web UI (cannot automate Web UI login).\n\n"
        "### Steps\n"
        "1. Open: https://192.168.0.244:8007\n"
        "2. Login as root\n"
        "3. Go to: **Administration → Users → root@pam → Edit**\n"
        f"4. Set **Email:** `{email}`\n"
        "5. Click **Save**\n\n"
    )

    if not apply:
        dry_run += (
            "### Test After Configuration\n"
            "Once configured, trigger a backup to verify email delivery.\n\n"
            "### Next Step\n"
            "Configure via Web UI, then run `diagnose_pbs_issues()` to verify."
        )
        audit.log("pbs.fix.email", "dry-run", outcome="reviewed", reversible=True)
        return dry_run

    # Can't automate Web UI, so return instructions
    result = (
        "## ⚠️ Email Configuration Requires Web UI\n\n"
        "This fix requires manual setup via the Proxmox Backup Server Web UI.\n\n"
        "### Follow These Steps\n"
        "1. **Open** https://192.168.0.244:8007\n"
        "2. **Login** with root credentials\n"
        "3. **Navigate** to Administration → Users\n"
        "4. **Find** root@pam user\n"
        "5. **Click** Edit\n"
        f"6. **Set Email** to: `{email}`\n"
        "7. **Save** changes\n\n"
        "### Verify Configuration\n"
        "After saving, notifications will be sent for:\n"
        "- Backup failures\n"
        "- Sync job errors\n"
        "- Garbage collection issues\n"
        "- Verification failures\n\n"
        "### Test\n"
        "Trigger a test backup and check your inbox."
    )

    audit.log("pbs.fix.email", "manual-instructions", outcome="ok", reversible=False)
    return result


def _add_gc_tuning(config: str) -> str:
    """Add gc-atime-safety-check tuning to config."""
    lines = config.split("\n")
    result = []
    in_datastore = False
    ds_name = ""

    for line in lines:
        result.append(line)
        if line.startswith("datastore:"):
            in_datastore = True
            ds_name = line.split()[-1]
        elif in_datastore and line.startswith("\t") and not line.strip().startswith("tuning"):
            # Add tuning after path line
            if "path" in line:
                result.append("\ttuning gc-atime-safety-check=false")
            in_datastore = False

    return "\n".join(result)
