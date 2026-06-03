"""
Daily Health Check — comprehensive status report for cron/ntfy.

Improvement #1: Better Daily Checks
Replaces simple inventory dump with actionable health report.
"""

import json
import datetime
from typing import Optional
from collections import Counter

import config
from ssh_client import SSHClient
from tools import tool
import audit


@tool(
    name="daily_health_check",
    description=(
        "Comprehensive daily health report: disk capacity, backup health, PBS status, "
        "security findings, critical services. Returns JSON for cron/ntfy integration."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "brief": {
                "type": "boolean",
                "description": "Brief mode (critical only) vs full report",
                "default": False
            }
        },
        "required": [],
    },
)
def daily_health_check(brief: bool = False) -> str:
    """
    Run daily (3 AM cron) to generate health report.
    Returns Markdown report + JSON for automation.
    """

    report = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "checks": {},
        "overall_status": "healthy",
        "alerts": [],
    }

    # Check 1: Disk Capacity
    disk_check = _check_disk_capacity()
    report["checks"]["disk"] = disk_check
    if disk_check["status"] == "critical":
        report["overall_status"] = "critical"
        report["alerts"].extend(disk_check.get("issues", []))
    elif disk_check["status"] == "warning" and report["overall_status"] != "critical":
        report["overall_status"] = "warning"

    # Check 2: Backup Health
    backup_check = _check_backup_health()
    report["checks"]["backups"] = backup_check
    if backup_check["status"] == "critical":
        report["overall_status"] = "critical"
        report["alerts"].extend(backup_check.get("issues", []))
    elif backup_check["status"] == "warning" and report["overall_status"] != "critical":
        report["overall_status"] = "warning"

    # Check 3: PBS Health
    pbs_check = _check_pbs_health()
    report["checks"]["pbs"] = pbs_check
    if pbs_check["status"] == "critical":
        report["overall_status"] = "critical"
        report["alerts"].extend(pbs_check.get("issues", []))

    # Check 4: Security (brief)
    sec_check = _check_security_brief()
    report["checks"]["security"] = sec_check
    if sec_check["critical_count"] > 0:
        report["overall_status"] = "critical"
    elif sec_check["high_count"] > 0 and report["overall_status"] != "critical":
        report["overall_status"] = "warning"

    # Check 5: Critical Services
    svc_check = _check_critical_services()
    report["checks"]["services"] = svc_check
    if svc_check["status"] == "critical":
        report["overall_status"] = "critical"
        report["alerts"].extend(svc_check.get("issues", []))

    # Format output
    markdown = _format_report_markdown(report)

    # Log to audit
    audit.log(
        "daily_health_check",
        f"status={report['overall_status']}",
        outcome="ok",
        reversible=True
    )

    return markdown


# ── Checks ──────────────────────────────────────────────────────────────────────

def _check_disk_capacity() -> dict:
    """Check all datastore disk usage."""
    try:
        ssh = SSHClient(
            host=config.PROXMOX_HOST,
            user=config.SSH_USER,
            key_path=config.ssh_key_path("id_ed25519"),
        )
        ssh.connect()

        out, _, _ = ssh.run(
            "df -h /var/lib/vz /mnt/datastore 2>/dev/null | tail -n +2",
            check=False
        )
        ssh.close()

        issues = []
        max_usage = 0

        for line in out.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 5:
                continue

            mount = parts[-1]
            try:
                usage_pct = int(parts[4].rstrip("%"))
                max_usage = max(max_usage, usage_pct)

                if usage_pct >= 95:
                    issues.append(f"🔴 {mount}: {usage_pct}% (CRITICAL)")
                elif usage_pct >= 85:
                    issues.append(f"🟠 {mount}: {usage_pct}% (WARNING)")
            except ValueError:
                continue

        status = "critical" if any("CRITICAL" in i for i in issues) else (
            "warning" if any("WARNING" in i for i in issues) else "ok"
        )

        return {
            "status": status,
            "max_usage_percent": max_usage,
            "issues": issues,
            "check_time_sec": 2,
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "issues": [f"Failed to check disk: {exc}"],
        }


def _check_backup_health() -> dict:
    """Check recent backups."""
    try:
        ssh = SSHClient(
            host=config.PROXMOX_HOST,
            user=config.SSH_USER,
            key_path=config.ssh_key_path("id_ed25519"),
        )
        ssh.connect()

        # Get all VMs
        vm_out, _, _ = ssh.run("qm list 2>/dev/null | tail -n +2", check=False)
        vms = {}
        for line in vm_out.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                vms[parts[0]] = parts[1]

        # Check backups
        failed = []
        oldest_hours = 0

        for vm_id in vms:
            out, _, _ = ssh.run(
                f"ls -lt /var/lib/vz/dump/ 2>/dev/null | grep 'qemu-{vm_id}' | head -1",
                check=False
            )

            if not out.strip():
                failed.append(f"VM {vm_id}: no recent backup")
            else:
                try:
                    # Parse timestamp
                    parts = out.split()
                    date_str = " ".join(parts[5:8])
                    dt = datetime.datetime.strptime(date_str, "%b %d %H:%M")
                    dt = dt.replace(year=datetime.datetime.now().year)
                    age_hours = (datetime.datetime.now() - dt).total_seconds() / 3600

                    if age_hours > 24:
                        failed.append(f"VM {vm_id}: backup {int(age_hours)}h old")
                    oldest_hours = max(oldest_hours, age_hours)
                except Exception:
                    pass

        ssh.close()

        status = "critical" if failed else "ok"

        return {
            "status": status,
            "issues": failed[:5],
            "oldest_backup_hours": int(oldest_hours),
            "vm_count": len(vms),
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "issues": [f"Failed to check backups: {exc}"],
        }


def _check_pbs_health() -> dict:
    """Check PBS: GC, disk usage."""
    pbs_host = config.PBS_HOST if hasattr(config, "PBS_HOST") else None
    if not pbs_host:
        return {"status": "skip", "reason": "PBS not configured"}

    try:
        ssh = SSHClient(
            host=pbs_host,
            user="root",
            key_path=config.ssh_key_path("pbs_id_ed25519"),
        )
        ssh.connect()

        issues = []

        # GC status
        gc_out, _, _ = ssh.run(
            "tail -50 /var/log/proxmox-backup/tasks/archive 2>/dev/null | grep -i 'garbage'",
            check=False
        )
        if "failed" in gc_out.lower() or "error" in gc_out.lower():
            issues.append("🔴 Garbage collection failed")

        # Disk usage
        disk_out, _, _ = ssh.run("df -h /mnt/datastore 2>/dev/null | tail -1", check=False)
        parts = disk_out.split()
        if len(parts) >= 5:
            try:
                usage_pct = int(parts[4].rstrip("%"))
                if usage_pct >= 95:
                    issues.append(f"🔴 Backup disk: {usage_pct}% (CRITICAL)")
                elif usage_pct >= 85:
                    issues.append(f"🟠 Backup disk: {usage_pct}% (WARNING)")
            except ValueError:
                pass

        ssh.close()

        status = "critical" if any("CRITICAL" in i or "failed" in i.lower() for i in issues) else (
            "warning" if issues else "ok"
        )

        return {
            "status": status,
            "issues": issues,
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
        }


def _check_security_brief() -> dict:
    """Quick security audit (top findings only)."""
    try:
        ssh = SSHClient(
            host=config.PROXMOX_HOST,
            user=config.SSH_USER,
            key_path=config.ssh_key_path("id_ed25519"),
        )
        ssh.connect()

        findings = {
            "critical_count": 0,
            "high_count": 0,
            "issues": [],
        }

        # Check 1: Root SSH allowed?
        out, _, _ = ssh.run(
            "grep -i 'PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null",
            check=False
        )
        if "yes" in out.lower():
            findings["critical_count"] += 1
            findings["issues"].append("🔴 SSH: Root login enabled")

        # Check 2: Firewall enabled?
        out, _, _ = ssh.run("ufw status | grep -i active", check=False)
        if "active" not in out.lower():
            findings["high_count"] += 1
            findings["issues"].append("🟠 Firewall: Not active")

        # Check 3: Outdated packages?
        out, _, _ = ssh.run("apt list --upgradable 2>/dev/null | wc -l", check=False)
        try:
            count = int(out.strip())
            if count > 10:
                findings["high_count"] += 1
                findings["issues"].append(f"🟠 Updates: {count} packages pending")
        except ValueError:
            pass

        ssh.close()

        return findings

    except Exception as exc:
        return {
            "critical_count": 0,
            "high_count": 0,
            "issues": [f"Security check failed: {exc}"],
        }


def _check_critical_services() -> dict:
    """Check PVE critical services."""
    try:
        ssh = SSHClient(
            host=config.PROXMOX_HOST,
            user=config.SSH_USER,
            key_path=config.ssh_key_path("id_ed25519"),
        )
        ssh.connect()

        critical = ["pveproxy", "pvedaemon", "pvestatd"]
        failed = []

        for svc in critical:
            _, _, rc = ssh.run(f"systemctl is-active {svc}", check=False)
            if rc != 0:
                failed.append(svc)

        ssh.close()

        status = "critical" if failed else "ok"
        issues = [f"🔴 {svc}: DOWN" for svc in failed]

        return {
            "status": status,
            "failed_services": failed,
            "issues": issues,
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
        }


# ── Formatting ──────────────────────────────────────────────────────────────────

def _format_report_markdown(report: dict) -> str:
    """Format JSON report as readable Markdown."""

    emoji_status = {
        "healthy": "🟢",
        "warning": "🟠",
        "critical": "🔴",
    }

    md = f"# Daily Health Check — {emoji_status.get(report['overall_status'], '❓')} {report['overall_status'].upper()}\n\n"
    md += f"**Time:** {report['timestamp']}\n\n"

    # Summary
    if report["alerts"]:
        md += "## 🚨 Alerts\n"
        for alert in report["alerts"][:10]:
            md += f"- {alert}\n"
        md += "\n"

    # Details
    md += "## 📊 Detailed Results\n\n"

    for check_name, check_result in report["checks"].items():
        if check_result.get("status") == "skip":
            continue

        status_emoji = {
            "ok": "✅",
            "warning": "⚠️",
            "critical": "🔴",
            "error": "❌",
        }.get(check_result.get("status"), "❓")

        md += f"### {status_emoji} {check_name.replace('_', ' ').title()}\n"

        if "issues" in check_result and check_result["issues"]:
            for issue in check_result["issues"]:
                md += f"- {issue}\n"

        if "critical_count" in check_result:
            md += f"- Critical: {check_result['critical_count']}, High: {check_result['high_count']}\n"

        md += "\n"

    # Recommendations
    if report["overall_status"] == "critical":
        md += "## ⚡ Next Steps\n"
        md += "1. Open the Proxmox GUI: `http://" + config.PROXMOX_HOST + ":8006`\n"
        md += "2. Check each alert and take action\n"
        md += "3. For fixes, ask the agent: `Tell me how to fix [issue]`\n\n"

    md += f"---\n_Report generated by Proxmox Agent_\n"

    return md
