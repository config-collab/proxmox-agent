"""
Inventory agent — queries PVE for all VMs, containers, storage, and disk state.
Returns structured data; formatting is the caller's responsibility.
"""
from dataclasses import dataclass, field
from typing import Optional
from proxmox_api import ProxmoxAPI
from ssh_client import SSHClient


@dataclass
class Guest:
    id: int
    name: str
    type: str          # "vm" | "lxc"
    status: str
    cpus: int
    maxmem_mb: int
    maxdisk_gb: float
    uptime_s: int
    tags: str = ""
    purpose: str = ""  # inferred


@dataclass
class StorageInfo:
    name: str
    type: str
    status: str
    total_gb: float
    used_gb: float
    avail_gb: float
    pct_used: float


@dataclass
class InventorySnapshot:
    node: str
    pve_version: str
    guests: list[Guest] = field(default_factory=list)
    storage: list[StorageInfo] = field(default_factory=list)
    disk_usage: str = ""
    failed_services: str = ""
    warnings: list[str] = field(default_factory=list)


def _infer_purpose(name: str, tags: str) -> str:
    """Heuristic: guess workload from name and tags."""
    tokens = (name + " " + tags).lower()
    mapping = {
        "voice":       "Voice assistant",
        "assistant":   "Voice assistant",
        "ha":          "Home Assistant",
        "homeassist":  "Home Assistant",
        "weather":     "Weather station",
        "station":     "Weather station",
        "pbs":         "Proxmox Backup Server",
        "backup":      "Backup",
        "pihole":      "DNS / ad-block",
        "dns":         "DNS",
        "nginx":       "Reverse proxy",
        "traefik":     "Reverse proxy",
        "portainer":   "Docker management",
        "docker":      "Docker host",
        "db":          "Database",
        "postgres":    "Database",
        "mysql":       "Database",
        "redis":       "Cache",
        "monitor":     "Monitoring",
        "grafana":     "Monitoring",
        "prometheus":  "Monitoring",
        "vaultwarden": "Password manager",
        "bitwarden":   "Password manager",
        "git":         "Git server",
        "gitea":       "Git server",
        "vpn":         "VPN",
        "wireguard":   "VPN",
    }
    for key, label in mapping.items():
        if key in tokens:
            return label
    return "?"


def _bytes_to_mb(b):
    return round(b / 1024 / 1024)


def _bytes_to_gb(b):
    return round(b / 1024 / 1024 / 1024, 1)


def collect(api: ProxmoxAPI, ssh: SSHClient, node: str = "pve") -> InventorySnapshot:
    snap = InventorySnapshot(node=node, pve_version="")

    # PVE version
    try:
        ver = api.version()
        snap.pve_version = ver.get("version", "unknown")
    except Exception as exc:
        snap.warnings.append(f"version check failed: {exc}")

    # VMs
    try:
        for vm in api.vms(node):
            g = Guest(
                id=vm["vmid"],
                name=vm.get("name", f"vm-{vm['vmid']}"),
                type="vm",
                status=vm.get("status", "unknown"),
                cpus=vm.get("cpus", 0),
                maxmem_mb=_bytes_to_mb(vm.get("maxmem", 0)),
                maxdisk_gb=_bytes_to_gb(vm.get("maxdisk", 0)),
                uptime_s=vm.get("uptime", 0),
                tags=vm.get("tags", ""),
            )
            g.purpose = _infer_purpose(g.name, g.tags)
            snap.guests.append(g)
    except Exception as exc:
        snap.warnings.append(f"VM list failed: {exc}")

    # LXC containers
    try:
        for ct in api.containers(node):
            g = Guest(
                id=ct["vmid"],
                name=ct.get("name", f"ct-{ct['vmid']}"),
                type="lxc",
                status=ct.get("status", "unknown"),
                cpus=ct.get("cpus", 0),
                maxmem_mb=_bytes_to_mb(ct.get("maxmem", 0)),
                maxdisk_gb=_bytes_to_gb(ct.get("maxdisk", 0)),
                uptime_s=ct.get("uptime", 0),
                tags=ct.get("tags", ""),
            )
            g.purpose = _infer_purpose(g.name, g.tags)
            snap.guests.append(g)
    except Exception as exc:
        snap.warnings.append(f"LXC list failed: {exc}")

    # Sort by ID
    snap.guests.sort(key=lambda g: g.id)

    # Storage
    try:
        for s in api.storage(node):
            total = s.get("total", 0)
            avail = s.get("avail", 0)
            used  = total - avail
            pct   = round(used / total * 100, 1) if total else 0
            si = StorageInfo(
                name=s.get("storage", "?"),
                type=s.get("type", "?"),
                status=s.get("status", "unknown"),
                total_gb=_bytes_to_gb(total),
                used_gb=_bytes_to_gb(used),
                avail_gb=_bytes_to_gb(avail),
                pct_used=pct,
            )
            snap.storage.append(si)
    except Exception as exc:
        snap.warnings.append(f"Storage list failed: {exc}")

    # Disk + service health via SSH
    try:
        out, _, _ = ssh.run("df -h / | tail -1", check=False)
        snap.disk_usage = out
    except Exception as exc:
        snap.warnings.append(f"df failed: {exc}")

    try:
        out, _, _ = ssh.run(
            "systemctl --failed --no-legend --plain 2>/dev/null | head -20",
            check=False,
        )
        snap.failed_services = out
    except Exception as exc:
        snap.warnings.append(f"systemctl --failed: {exc}")

    return snap


def render(snap: InventorySnapshot) -> str:
    lines = []
    lines.append(f"## Inventory — node `{snap.node}`  (PVE {snap.pve_version})")
    lines.append("")

    # Guests table
    running  = [g for g in snap.guests if g.status == "running"]
    stopped  = [g for g in snap.guests if g.status != "running"]
    lines.append(f"**Guests:** {len(snap.guests)} total — "
                 f"{len(running)} running, {len(stopped)} stopped")
    lines.append("")
    lines.append("| ID | Name | Type | Status | vCPU | RAM MB | Disk GB | Purpose |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for g in snap.guests:
        uptime = f"{g.uptime_s // 3600}h" if g.uptime_s else "—"
        status = g.status
        if g.status == "running":
            status = f"up {uptime}"
        lines.append(
            f"| {g.id} | {g.name} | {g.type} | {status} "
            f"| {g.cpus} | {g.maxmem_mb} | {g.maxdisk_gb} | {g.purpose} |"
        )

    lines.append("")
    lines.append("### Storage")
    lines.append("| Name | Type | Status | Used GB | Total GB | % |")
    lines.append("|---|---|---|---|---|---|")
    for s in snap.storage:
        warn = " ⚠" if s.pct_used >= 80 else ""
        lines.append(
            f"| {s.name} | {s.type} | {s.status} "
            f"| {s.used_gb} | {s.total_gb} | {s.pct_used}%{warn} |"
        )

    if snap.disk_usage:
        lines.append("")
        lines.append(f"**Host root disk:** `{snap.disk_usage}`")

    if snap.failed_services:
        lines.append("")
        lines.append("### Failed services")
        lines.append(f"```\n{snap.failed_services}\n```")

    unknown = [g for g in snap.guests if g.purpose == "?"]
    if unknown:
        lines.append("")
        lines.append("### Unknown purpose — needs owner review")
        for g in unknown:
            lines.append(f"- `{g.id}` {g.name} ({g.type})")

    if snap.warnings:
        lines.append("")
        lines.append("### Warnings")
        for w in snap.warnings:
            lines.append(f"- {w}")

    return "\n".join(lines)
