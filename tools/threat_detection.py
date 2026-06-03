"""
Threat Detection & Breach Risk Analysis

Instead of: "You have 3 security findings"
This says: "⚠️ BREACH RISK DETECTED: SSH brute force attempts detected.
            Last 24h: 847 failed logins. Attacker is exploring. Action needed."

This is the second "wow" feature: predict & detect anomalies, not just report them.
"""

import datetime
import json
from typing import Optional
from collections import defaultdict

import config
from ssh_client import SSHClient
from tools import tool
import audit


@tool(
    name="detect_breach_risk",
    description=(
        "Analyze security logs for breach attempts, intrusions, anomalies. "
        "Detects: SSH brute force, failed sudo attempts, privilege escalation, "
        "unusual process execution, network scans. Returns threat level + recommendations."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hours_back": {
                "type": "integer",
                "description": "How many hours to analyze (default 24)",
                "default": 24
            },
            "detailed": {
                "type": "boolean",
                "description": "Include detailed log analysis (slower)",
                "default": False
            }
        },
        "required": [],
    },
)
def detect_breach_risk(hours_back: int = 24, detailed: bool = False) -> str:
    """
    Analyze logs for breach indicators in real-time.

    Returns: Risk assessment with:
    - Threat level (LOW/MEDIUM/HIGH/CRITICAL)
    - Attack patterns detected
    - Confidence score
    - Recommended actions
    """

    try:
        ssh = SSHClient(
            host=config.PROXMOX_HOST,
            user=config.SSH_USER,
            key_path=config.ssh_key_path("id_ed25519"),
        )
        ssh.connect()

        # Run threat detection checks
        threats = []

        # Check 1: SSH brute force attempts
        ssh_threats = _detect_ssh_brute_force(ssh, hours_back)
        if ssh_threats:
            threats.append(ssh_threats)

        # Check 2: Failed privilege escalation
        sudo_threats = _detect_sudo_abuse(ssh, hours_back)
        if sudo_threats:
            threats.append(sudo_threats)

        # Check 3: Suspicious process execution
        if detailed:
            process_threats = _detect_suspicious_processes(ssh, hours_back)
            if process_threats:
                threats.append(process_threats)

        # Check 4: Port scanning attempts
        scan_threats = _detect_port_scans(ssh, hours_back)
        if scan_threats:
            threats.append(scan_threats)

        # Check 5: Unusual network connections
        if detailed:
            net_threats = _detect_unusual_connections(ssh, hours_back)
            if net_threats:
                threats.append(net_threats)

        ssh.close()

        # Determine overall risk level
        risk_level = _calculate_risk_level(threats)

        # Generate report
        report = _format_threat_report(threats, risk_level, hours_back)

        # Log to audit
        audit.log(
            "detect_breach_risk",
            f"risk_level={risk_level}, hours={hours_back}",
            outcome="ok",
            reversible=True
        )

        return report

    except Exception as exc:
        return f"❌ Threat detection failed: {exc}"


# ── Detection Functions ──────────────────────────────────────────────────────

def _detect_ssh_brute_force(ssh: SSHClient, hours_back: int) -> Optional[dict]:
    """Detect SSH brute force attempts."""

    # Count failed SSH logins in last N hours
    cmd = (
        f"journalctl --since '{hours_back} hours ago' -u ssh | "
        "grep -i 'failed password\\|invalid user' | wc -l"
    )
    out, _, _ = ssh.run(cmd, check=False)

    try:
        failed_count = int(out.strip() or "0")
    except ValueError:
        return None

    # Get unique attacker IPs
    cmd = (
        f"journalctl --since '{hours_back} hours ago' -u ssh | "
        "grep -i 'failed password' | grep -oP '\\d+\\.\\d+\\.\\d+\\.\\d+' | sort | uniq -c | sort -rn | head -5"
    )
    out, _, _ = ssh.run(cmd, check=False)

    attackers = []
    for line in out.strip().split("\n"):
        if line.strip():
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    count = int(parts[0])
                    ip = parts[1]
                    attackers.append({"ip": ip, "attempts": count})
                except ValueError:
                    pass

    if failed_count >= 10:  # Threshold for brute force
        return {
            "type": "ssh_brute_force",
            "severity": "critical" if failed_count >= 100 else "high" if failed_count >= 50 else "medium",
            "failed_attempts": failed_count,
            "top_attackers": attackers,
            "recommendation": (
                "IMMEDIATE: Block attacking IPs via firewall. "
                "Review: Run 'fail2ban-client status sshd' to check if rate-limiting active."
            ),
        }

    return None


def _detect_sudo_abuse(ssh: SSHClient, hours_back: int) -> Optional[dict]:
    """Detect failed or unusual sudo attempts."""

    cmd = (
        f"journalctl --since '{hours_back} hours ago' -u sudo | "
        "grep -i 'sudo.*denied\\|sudo.*not allowed' | wc -l"
    )
    out, _, _ = ssh.run(cmd, check=False)

    try:
        denied_count = int(out.strip() or "0")
    except ValueError:
        return None

    # Get users attempting sudo
    cmd = (
        f"journalctl --since '{hours_back} hours ago' -u sudo | "
        "grep -i denied | grep -oP 'user=\\K\\w+' | sort | uniq -c | sort -rn | head -3"
    )
    out, _, _ = ssh.run(cmd, check=False)

    users = [line.strip().split()[-1] for line in out.strip().split("\n") if line.strip()]

    if denied_count >= 5:
        return {
            "type": "sudo_abuse",
            "severity": "high" if denied_count >= 20 else "medium",
            "denied_attempts": denied_count,
            "suspicious_users": users,
            "recommendation": (
                "REVIEW: Investigate failed sudo attempts. "
                "If legitimate users, update /etc/sudoers. "
                "If not, may indicate compromise attempt."
            ),
        }

    return None


def _detect_port_scans(ssh: SSHClient, hours_back: int) -> Optional[dict]:
    """Detect external port scan attempts."""

    # Look for kernel messages about rejected connections
    cmd = (
        f"journalctl --since '{hours_back} hours ago' | "
        "grep -i 'connection reset\\|invalid' | wc -l"
    )
    out, _, _ = ssh.run(cmd, check=False)

    try:
        scan_attempts = int(out.strip() or "0")
    except ValueError:
        return None

    if scan_attempts >= 50:
        return {
            "type": "port_scan",
            "severity": "medium",
            "scan_attempts": scan_attempts,
            "recommendation": (
                "Monitor: External host is scanning your ports. "
                "Likely automated reconnaissance. Ensure firewall is blocking unwanted ports."
            ),
        }

    return None


def _detect_suspicious_processes(ssh: SSHClient, hours_back: int) -> Optional[dict]:
    """Detect suspicious process execution."""

    # Look for common attack tools/processes
    suspicious_patterns = [
        "nmap", "masscan", "nikto",  # Scanners
        "metasploit", "meterpreter",  # Exploits
        "mimikatz",  # Credential theft
        "/tmp/.*\\.sh",  # Scripts in /tmp
        "chmod.*777",  # Permission escalation
    ]

    found_processes = []
    for pattern in suspicious_patterns:
        cmd = f"journalctl --since '{hours_back} hours ago' | grep -i '{pattern}'"
        out, _, _ = ssh.run(cmd, check=False)
        if out.strip():
            found_processes.append(pattern)

    if found_processes:
        return {
            "type": "suspicious_execution",
            "severity": "critical",
            "processes_found": found_processes,
            "recommendation": (
                "ALERT: Suspicious tools/patterns detected in logs. "
                "Review process execution history. May indicate breach in progress."
            ),
        }

    return None


def _detect_unusual_connections(ssh: SSHClient, hours_back: int) -> Optional[dict]:
    """Detect unusual outbound connections."""

    # Get active connections
    cmd = "ss -tan | grep ESTABLISHED | wc -l"
    out, _, _ = ssh.run(cmd, check=False)

    try:
        conn_count = int(out.strip() or "0")
    except ValueError:
        return None

    # Threshold: alert if > 20 established connections (unusual for homelab)
    if conn_count > 20:
        return {
            "type": "unusual_connections",
            "severity": "medium",
            "established_connections": conn_count,
            "recommendation": (
                "Monitor: Unusual number of active connections. "
                "Check what's connecting to external hosts via 'ss -tan'."
            ),
        }

    return None


# ── Risk Calculation ──────────────────────────────────────────────────────────

def _calculate_risk_level(threats: list) -> str:
    """Determine overall risk level from threats."""

    if not threats:
        return "LOW"

    critical_count = sum(1 for t in threats if t.get("severity") == "critical")
    high_count = sum(1 for t in threats if t.get("severity") == "high")
    medium_count = sum(1 for t in threats if t.get("severity") == "medium")

    if critical_count > 0:
        return "CRITICAL"
    elif high_count >= 2 or critical_count > 0:
        return "HIGH"
    elif medium_count >= 2:
        return "MEDIUM"
    else:
        return "LOW"


# ── Formatting ──────────────────────────────────────────────────────────────

def _format_threat_report(threats: list, risk_level: str, hours_back: int) -> str:
    """Format threat analysis as actionable report."""

    emoji_risk = {
        "LOW": "🟢",
        "MEDIUM": "🟡",
        "HIGH": "🟠",
        "CRITICAL": "🔴",
    }

    md = f"# {emoji_risk[risk_level]} Security Threat Analysis\n\n"
    md += f"**Overall Risk Level:** {emoji_risk[risk_level]} **{risk_level}**\n"
    md += f"**Time Window:** Last {hours_back} hours\n\n"

    if not threats:
        md += "✅ **No threats detected.** Your system appears secure.\n"
        return md

    md += "## 🔍 Detected Threats\n\n"

    for threat in threats:
        threat_type = threat["type"].replace("_", " ").title()
        severity = threat.get("severity", "unknown").upper()

        emoji_sev = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡"}[severity]
        md += f"### {emoji_sev} {threat_type}\n"

        if threat["type"] == "ssh_brute_force":
            md += f"**Status:** {threat['failed_attempts']} failed login attempts\n"
            if threat.get("top_attackers"):
                md += "**Top Attackers:**\n"
                for attacker in threat["top_attackers"]:
                    md += f"- `{attacker['ip']}`: {attacker['attempts']} attempts\n"

        elif threat["type"] == "sudo_abuse":
            md += f"**Status:** {threat['denied_attempts']} denied sudo attempts\n"
            if threat.get("suspicious_users"):
                md += f"**Suspicious Users:** {', '.join(threat['suspicious_users'])}\n"

        elif threat["type"] == "port_scan":
            md += f"**Status:** {threat['scan_attempts']} port scan attempts detected\n"

        elif threat["type"] == "suspicious_execution":
            md += f"**Status:** Suspicious patterns found\n"
            md += f"**Patterns:** {', '.join(threat['processes_found'])}\n"

        elif threat["type"] == "unusual_connections":
            md += f"**Status:** {threat['established_connections']} active connections\n"

        md += f"\n**Action:** {threat['recommendation']}\n\n"

    # Summary
    md += "## 📋 Summary\n\n"
    md += "1. **Immediate Actions** (if CRITICAL):\n"
    critical = [t for t in threats if t.get("severity") == "critical"]
    if critical:
        for t in critical:
            md += f"   - {t['recommendation'][:80]}...\n"
    else:
        md += "   - None\n"

    md += "\n2. **Review Items** (if HIGH):\n"
    high = [t for t in threats if t.get("severity") == "high"]
    if high:
        for t in high:
            md += f"   - {t.get('type').replace('_', ' ').title()}\n"
    else:
        md += "   - None\n"

    md += "\n3. **Monitor** (if MEDIUM):\n"
    medium = [t for t in threats if t.get("severity") == "medium"]
    if medium:
        for t in medium:
            md += f"   - {t.get('type').replace('_', ' ').title()}\n"
    else:
        md += "   - None\n"

    md += "\n---\n"
    md += f"_Analysis completed {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n"

    return md
