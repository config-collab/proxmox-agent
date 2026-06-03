"""
Security audit agent.
Checks PVE host hardening and per-guest exposure.
Never makes changes — read-only assessment only.
"""
from dataclasses import dataclass, field
import ssl
import socket
import datetime
from ssh_client import SSHClient
import config


SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}


@dataclass
class Finding:
    severity: str    # CRITICAL | HIGH | MEDIUM | INFO
    target: str      # "host" | guest name
    category: str    # ssh | firewall | ports | tls | packages | files
    title: str
    detail: str


@dataclass
class SecurityReport:
    host_findings: list[Finding] = field(default_factory=list)
    guest_findings: list[Finding] = field(default_factory=list)
    tls_findings: list[Finding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def all_findings(self) -> list[Finding]:
        all_ = self.host_findings + self.guest_findings + self.tls_findings
        return sorted(all_, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))

    def by_severity(self, sev: str) -> list[Finding]:
        return [f for f in self.all_findings() if f.severity == sev]


# ── PVE host checks ────────────────────────────────────────────────────────────

def _check_host_ssh(ssh: SSHClient) -> list[Finding]:
    findings = []
    out, _, _ = ssh.run("sshd -T 2>/dev/null || cat /etc/ssh/sshd_config", check=False)

    def val(key: str) -> str:
        for line in out.lower().splitlines():
            if line.startswith(key.lower()):
                return line.split()[-1] if line.split() else ""
        return ""

    if val("permitrootlogin") not in ("prohibit-password", "no", "forced-commands-only"):
        findings.append(Finding("HIGH", "host", "ssh",
            "Root SSH login allows passwords",
            f"PermitRootLogin={val('permitrootlogin') or 'not set'} — "
            "set to 'prohibit-password' to require key auth"))

    if val("passwordauthentication") in ("yes", ""):
        findings.append(Finding("HIGH", "host", "ssh",
            "SSH password authentication enabled on PVE host",
            "PasswordAuthentication should be 'no' — keys only"))

    protocol = val("protocol")
    if protocol and protocol != "2":
        findings.append(Finding("CRITICAL", "host", "ssh",
            "SSH Protocol 1 enabled", "Set 'Protocol 2' in sshd_config"))

    return findings


def _check_host_firewall(ssh: SSHClient) -> list[Finding]:
    findings = []
    out, _, rc = ssh.run("pvesh get /cluster/firewall/options --output-format json 2>/dev/null", check=False)
    if "enable" not in out or '"enable": 1' not in out.replace(" ", ""):
        findings.append(Finding("HIGH", "host", "firewall",
            "Proxmox datacenter firewall not enabled",
            "Enable in Datacenter → Firewall → Options → Firewall: Yes"))

    out2, _, _ = ssh.run("iptables -L INPUT --line-numbers -n 2>/dev/null | head -30", check=False)
    if not out2 or "ACCEPT" not in out2:
        findings.append(Finding("MEDIUM", "host", "firewall",
            "No iptables INPUT rules found",
            "Consider enabling the PVE firewall to restrict management access"))

    return findings


def _check_host_ports(ssh: SSHClient) -> list[Finding]:
    findings = []
    out, _, _ = ssh.run("ss -tlnp 2>/dev/null | tail -n +2", check=False)
    exposed = []
    risky_ports = {
        "5900": "VNC (unencrypted remote desktop)",
        "5901": "VNC",
        "23":   "Telnet (plaintext)",
        "21":   "FTP (plaintext)",
        "2049": "NFS (check if intentional)",
    }
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            addr = parts[3]
            port = addr.split(":")[-1]
            if port in risky_ports and "0.0.0.0" in addr or "*:" in addr:
                exposed.append(f":{port} — {risky_ports[port]}")

    for e in exposed:
        findings.append(Finding("HIGH", "host", "ports",
            f"Risky service exposed: {e}",
            "Restrict to management network or disable if unused"))

    return findings


def _check_host_pve_version(ssh: SSHClient) -> list[Finding]:
    findings = []
    out, _, _ = ssh.run("pveversion 2>/dev/null", check=False)
    if out:
        findings.append(Finding("INFO", "host", "packages",
            f"PVE version: {out.strip()}",
            "Verify this is the latest stable release at pve.proxmox.com/wiki/Roadmap"))
    return findings


def _check_host_failed_services(ssh: SSHClient) -> list[Finding]:
    findings = []
    out, _, _ = ssh.run("systemctl --failed --no-legend --plain 2>/dev/null", check=False)
    if out.strip():
        findings.append(Finding("MEDIUM", "host", "services",
            "Failed systemd services on PVE host",
            f"Run 'systemctl --failed' to investigate:\n{out.strip()}"))
    return findings


def check_host(ssh: SSHClient) -> list[Finding]:
    findings = []
    for fn in [
        _check_host_ssh,
        _check_host_firewall,
        _check_host_ports,
        _check_host_pve_version,
        _check_host_failed_services,
    ]:
        try:
            findings.extend(fn(ssh))
        except Exception as exc:
            findings.append(Finding("INFO", "host", "error",
                f"Check failed: {fn.__name__}", str(exc)))
    return findings


# ── Per-guest checks ───────────────────────────────────────────────────────────

def _guest_check_ssh(ssh: SSHClient, name: str) -> list[Finding]:
    findings = []
    out, _, rc = ssh.run("sshd -T 2>/dev/null || cat /etc/ssh/sshd_config 2>/dev/null", check=False)
    if rc != 0 or not out:
        return findings

    def val(key):
        for line in out.lower().splitlines():
            if line.startswith(key.lower()):
                return line.split()[-1] if line.split() else ""
        return ""

    if val("passwordauthentication") in ("yes", ""):
        findings.append(Finding("MEDIUM", name, "ssh",
            "SSH password auth enabled",
            "Set PasswordAuthentication no — keys are already deployed"))
    if val("permitrootlogin") == "yes":
        findings.append(Finding("MEDIUM", name, "ssh",
            "Root SSH login with password allowed",
            "Set PermitRootLogin prohibit-password"))
    return findings


def _guest_check_ports(ssh: SSHClient, name: str) -> list[Finding]:
    findings = []
    out, _, _ = ssh.run("ss -tlnp 2>/dev/null | tail -n +2", check=False)
    risky = {"5900": "VNC", "5901": "VNC", "23": "Telnet", "21": "FTP"}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        port = parts[3].split(":")[-1]
        if port in risky:
            findings.append(Finding("HIGH", name, "ports",
                f"Risky port open: {port} ({risky[port]})",
                "Disable or restrict to internal network only"))
    return findings


def _guest_check_writable_etc(ssh: SSHClient, name: str) -> list[Finding]:
    findings = []
    out, _, rc = ssh.run(
        "find /etc -maxdepth 3 -writable -type f 2>/dev/null | grep -v '.pyc' | head -10",
        check=False, timeout=15,
    )
    if rc == 0 and out.strip():
        findings.append(Finding("HIGH", name, "files",
            "World-writable files found in /etc",
            f"Review and fix permissions:\n{out.strip()}"))
    return findings


def _guest_check_updates(ssh: SSHClient, name: str) -> list[Finding]:
    findings = []
    out, _, rc = ssh.run(
        "apt-get -s dist-upgrade 2>/dev/null | grep '^Inst' | wc -l || "
        "apk list --upgrades 2>/dev/null | wc -l",
        check=False, timeout=30,
    )
    try:
        n = int(out.strip())
        if n > 0:
            sev = "HIGH" if n > 10 else "MEDIUM"
            findings.append(Finding(sev, name, "packages",
                f"{n} pending package update(s)",
                "Run check_patches for details and apply security updates first"))
    except ValueError:
        pass
    return findings


def check_guest(name: str, ip: str, key_path: str, user: str = "root") -> list[Finding]:
    findings = []
    try:
        ssh = SSHClient(host=ip, user=user, key_path=key_path)
        ssh.connect()
        for fn in [_guest_check_ssh, _guest_check_ports,
                   _guest_check_writable_etc, _guest_check_updates]:
            try:
                findings.extend(fn(ssh, name))
            except Exception as exc:
                findings.append(Finding("INFO", name, "error",
                    f"Check failed: {fn.__name__}", str(exc)))
        ssh.close()
    except Exception as exc:
        findings.append(Finding("INFO", name, "reachability",
            f"Could not connect to {name} ({ip})", str(exc)))
    return findings


# ── TLS certificate checks ─────────────────────────────────────────────────────

def check_tls(host: str, port: int = 8006, label: str = "Proxmox web UI") -> Finding | None:
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                if not cert:
                    return Finding("MEDIUM", label, "tls",
                        "Could not retrieve TLS certificate", "")
                not_after = datetime.datetime.strptime(
                    cert["notAfter"], "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=datetime.timezone.utc)
                days_left = (not_after - datetime.datetime.now(datetime.timezone.utc)).days
                if days_left < 0:
                    return Finding("CRITICAL", label, "tls",
                        f"TLS certificate EXPIRED {abs(days_left)}d ago",
                        f"Renew immediately — expired {not_after.strftime('%Y-%m-%d')}")
                if days_left < 14:
                    return Finding("HIGH", label, "tls",
                        f"TLS certificate expires in {days_left} days",
                        f"Renew before {not_after.strftime('%Y-%m-%d')}")
                if days_left < 30:
                    return Finding("MEDIUM", label, "tls",
                        f"TLS certificate expires in {days_left} days",
                        f"Plan renewal before {not_after.strftime('%Y-%m-%d')}")
                return Finding("INFO", label, "tls",
                    f"TLS certificate valid for {days_left} days",
                    f"Expires {not_after.strftime('%Y-%m-%d')}")
    except Exception as exc:
        return Finding("INFO", label, "tls", f"TLS check failed: {exc}", "")


# ── Full audit ─────────────────────────────────────────────────────────────────

def run_full_audit(pve_ssh: SSHClient) -> SecurityReport:
    report = SecurityReport()

    print("  [security] checking PVE host ...")
    report.host_findings = check_host(pve_ssh)

    print("  [security] checking TLS certificates ...")
    tls = check_tls(config.PROXMOX_HOST, config.PROXMOX_PORT, "Proxmox web UI")
    if tls:
        report.tls_findings.append(tls)

    print("  [security] checking guests ...")
    conns = config.guest_connections()
    for name, conn in conns.items():
        if not conn["ip"] or not conn["key_path"]:
            continue
        print(f"    → {name} ({conn['ip']})")
        findings = check_guest(name, conn["ip"], conn["key_path"], conn["user"])
        report.guest_findings.extend(findings)

    return report


# ── Render ─────────────────────────────────────────────────────────────────────

def render(report: SecurityReport) -> str:
    lines = ["## Security audit report\n"]
    all_ = report.all_findings()

    counts = {s: len(report.by_severity(s)) for s in SEVERITY_ORDER}
    lines.append(
        f"**{counts['CRITICAL']} CRITICAL · {counts['HIGH']} HIGH · "
        f"{counts['MEDIUM']} MEDIUM · {counts['INFO']} INFO**\n"
    )

    for sev in ("CRITICAL", "HIGH", "MEDIUM", "INFO"):
        items = report.by_severity(sev)
        if not items:
            continue
        lines.append(f"### [{sev}]")
        for f in items:
            lines.append(f"**{f.target} / {f.category}** — {f.title}")
            if f.detail:
                lines.append(f"  > {f.detail}")
        lines.append("")

    return "\n".join(lines)
