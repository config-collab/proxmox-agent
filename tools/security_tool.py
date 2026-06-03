"""
Security tool — LLM-callable wrapper around security.py.
"""
import audit
import security
from tools import tool
from ssh_client import SSHClient


@tool(
    name="security_audit",
    description="Security audit: SSH hardening, firewall, open ports, writable files, pending CVEs, TLS expiry. Findings by severity.",
    input_schema={
        "type": "object",
        "properties": {
            "guest_name": {"type": "string", "description": "Single guest. Omit = all."},
            "host_only": {"type": "boolean", "description": "PVE host only, skip guests."},
        },
        "required": [],
    },
)
def security_audit(guest_name: str = "", host_only: bool = False) -> str:
    import config

    report = security.SecurityReport()

    with SSHClient() as pve_ssh:
        print("  [security] checking PVE host ...")
        report.host_findings = security.check_host(pve_ssh)

        tls = security.check_tls(config.PROXMOX_HOST, config.PROXMOX_PORT, "Proxmox web UI")
        if tls:
            report.tls_findings.append(tls)

    if not host_only:
        conns = config.guest_connections()
        targets = (
            {guest_name: conns[guest_name]}
            if guest_name and guest_name in conns
            else conns
        )
        if guest_name and guest_name not in conns:
            return f"No connection info for guest {guest_name!r}."

        for name, conn in targets.items():
            if not conn["ip"] or not conn["key_path"]:
                continue
            print(f"  [security] → {name} ({conn['ip']})")
            findings = security.check_guest(name, conn["ip"], conn["key_path"], conn["user"])
            report.guest_findings.extend(findings)

    audit.log(
        "security.audit",
        guest_name or "all",
        outcome="ok",
        reversible=True,
        critical=len(report.by_severity("CRITICAL")),
        high=len(report.by_severity("HIGH")),
    )
    return security.render(report)
