"""
VM/Container management tools — lifecycle, metrics, snapshots.
"""
import datetime
import audit
from tools import tool
from proxmox_api import ProxmoxAPI


# ── Shared helper ──────────────────────────────────────────────────────────────

def _find_guest(api: ProxmoxAPI, node: str, name: str) -> tuple[int | None, str | None]:
    """Locate a guest by name on the node. Returns (vmid, 'qemu'|'lxc') or (None, None)."""
    try:
        for vm in api.vms(node):
            if vm.get("name") == name:
                return vm["vmid"], "qemu"
        for ct in api.containers(node):
            if ct.get("name") == name:
                return ct["vmid"], "lxc"
    except Exception:
        pass
    return None, None


# ── manage_vm ─────────────────────────────────────────────────────────────────

@tool(
    name="manage_vm",
    description=(
        "Start, stop, shutdown, restart, or get status of a VM or LXC by name. "
        "status is read-only. stop/shutdown/restart require user confirmation — "
        "always dry-run or describe first unless user explicitly confirmed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name":   {"type": "string", "description": "VM or container name (not VMID)."},
            "action": {
                "type": "string",
                "enum": ["start", "stop", "shutdown", "restart", "status"],
                "description": "start=power on, stop=force off, shutdown=graceful ACPI, restart=reboot, status=current state",
            },
            "node": {"type": "string", "description": "PVE node name (default: pve)."},
        },
        "required": ["name", "action"],
    },
)
def manage_vm(name: str, action: str, node: str = "pve") -> str:
    api = ProxmoxAPI(); api.login()
    vmid, gtype = _find_guest(api, node, name)
    if vmid is None:
        return f"'{name}' not found on {node} — verify name with get_inventory."

    base = f"/nodes/{node}/{gtype}/{vmid}"

    if action == "status":
        info = api.get(f"{base}/status/current")
        st       = info.get("status", "unknown")
        cpu_pct  = round(info.get("cpu", 0) * 100, 1)
        mem_mb   = round(info.get("mem", 0) / 1024 / 1024)
        maxmem   = round(info.get("maxmem", 0) / 1024 / 1024)
        uptime_s = info.get("uptime", 0)
        uptime   = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m" if uptime_s else "—"
        return (
            f"**{name}** [{gtype} {vmid}] — {st}\n"
            f"CPU: {cpu_pct}%   RAM: {mem_mb}/{maxmem} MB   Uptime: {uptime}"
        )

    ep_map = {"start": "start", "stop": "stop", "shutdown": "shutdown", "restart": "reboot"}
    ep = ep_map.get(action)
    if not ep:
        return f"Unknown action '{action}'."

    result = api.post(f"{base}/status/{ep}")
    audit.log(f"vm.{action}", f"{name} ({gtype}/{vmid})", outcome="ok",
              reversible=(action == "start"))
    return f"[{action.upper()}] {name} ({gtype} {vmid}) — task started. UPID: {str(result)[:40]}"


# ── get_metrics ───────────────────────────────────────────────────────────────

@tool(
    name="get_metrics",
    description=(
        "CPU, RAM, disk I/O, and network trends for a VM, container, or the Proxmox host. "
        "Use when diagnosing performance issues or checking resource pressure."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "VM/container name, or 'host' for the PVE node itself.",
            },
            "timeframe": {
                "type": "string",
                "enum": ["hour", "day", "week"],
                "description": "Time window to query (default: hour).",
            },
            "node": {"type": "string", "description": "PVE node (default: pve)."},
        },
        "required": ["name"],
    },
)
def get_metrics(name: str, timeframe: str = "hour", node: str = "pve") -> str:
    api = ProxmoxAPI(); api.login()

    if name.lower() in ("host", "node", "pve", node):
        path  = f"/nodes/{node}/rrddata"
        title = f"Host ({node})"
    else:
        vmid, gtype = _find_guest(api, node, name)
        if vmid is None:
            return f"'{name}' not found."
        path  = f"/nodes/{node}/{gtype}/{vmid}/rrddata"
        title = f"{name} ({gtype} {vmid})"

    data = api.get(f"{path}?timeframe={timeframe}&cf=AVERAGE")
    if not data:
        return f"No metrics available for {title}."

    return _render_metrics(title, data, timeframe)


def _sparkline(vals: list[float], width: int = 24) -> str:
    bars = "▁▂▃▄▅▆▇█"
    if not vals or max(vals or [0]) == 0:
        return "▁" * width
    mn, mx = min(vals), max(vals)
    span = mx - mn or 1
    chunk = max(1, len(vals) // width)
    points = [max(vals[i: i + chunk] or [0]) for i in range(0, len(vals), chunk)][:width]
    return "".join(bars[min(int((v - mn) / span * (len(bars) - 1)), len(bars) - 1)] for v in points)


def _hfmt(val: float) -> str:
    if val >= 1024 ** 3:
        return f"{val/1024**3:.1f} GB"
    if val >= 1024 ** 2:
        return f"{val/1024**2:.0f} MB"
    if val >= 1024:
        return f"{val/1024:.0f} KB"
    return f"{val:.0f} B"


def _render_metrics(title: str, data: list[dict], timeframe: str) -> str:
    def col(key):
        return [r[key] for r in data if r.get(key) is not None]

    cpu   = col("cpu")
    mem   = col("mem")
    maxm  = next((r.get("maxmem") for r in reversed(data) if r.get("maxmem")), 0)
    di    = [r.get("diskread", 0) + r.get("diskwrite", 0) for r in data]
    ni    = [r.get("netin", 0) + r.get("netout", 0) for r in data]

    avg = lambda v: sum(v) / len(v) if v else 0

    lines = [f"## Metrics — {title}  (last {timeframe})\n"]

    if cpu:
        lines.append(f"**CPU**    peak {max(cpu)*100:.1f}%  avg {avg(cpu)*100:.1f}%")
        lines.append(f"  `{_sparkline(cpu)}`\n")
    if mem and maxm:
        lines.append(f"**RAM**    {_hfmt(max(mem))} peak / {_hfmt(maxm)} total")
        lines.append(f"  `{_sparkline([m/maxm for m in mem])}`\n")
    if any(di):
        lines.append(f"**Disk I/O**   {_hfmt(sum(di))} total")
        lines.append(f"  `{_sparkline(di)}`\n")
    if any(ni):
        lines.append(f"**Network**   {_hfmt(sum(ni))} total")
        lines.append(f"  `{_sparkline(ni)}`")

    return "\n".join(lines)


# ── manage_snapshots ──────────────────────────────────────────────────────────

@tool(
    name="manage_snapshots",
    description=(
        "List, create, rollback, or delete snapshots for a VM or LXC. "
        "Create before risky changes; rollback to undo. "
        "Rollback is irreversible — always confirm with user first."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "VM or container name."},
            "action": {
                "type": "string",
                "enum": ["list", "create", "rollback", "delete"],
                "description": "list = show all, create = take new, rollback = restore, delete = remove.",
            },
            "snap_name": {
                "type": "string",
                "description": "Snapshot name. Required for create/rollback/delete.",
            },
            "description": {
                "type": "string",
                "description": "Description for the new snapshot.",
            },
            "node": {"type": "string", "description": "PVE node (default: pve)."},
        },
        "required": ["name", "action"],
    },
)
def manage_snapshots(
    name: str, action: str, snap_name: str = "",
    description: str = "", node: str = "pve",
) -> str:
    api = ProxmoxAPI(); api.login()
    vmid, gtype = _find_guest(api, node, name)
    if vmid is None:
        return f"'{name}' not found on {node}."

    base = f"/nodes/{node}/{gtype}/{vmid}/snapshot"

    if action == "list":
        snaps = api.get(base) or []
        visible = [s for s in snaps if s.get("name") != "current"]
        if not visible:
            return f"No snapshots for {name}."
        lines = [f"Snapshots for **{name}** ({gtype} {vmid}):\n",
                 "| Name | Description | Created |", "|---|---|---|"]
        for s in sorted(visible, key=lambda x: x.get("snaptime", 0), reverse=True):
            ts = s.get("snaptime", 0)
            dt = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"
            desc = (s.get("description") or "")[:40]
            lines.append(f"| {s.get('name','?')} | {desc} | {dt} |")
        return "\n".join(lines)

    if action == "create":
        snap = snap_name or f"snap-{datetime.datetime.now().strftime('%Y%m%d-%H%M')}"
        api.post(base, {"snapname": snap, "description": description or "manual snapshot"})
        audit.log("snapshot.create", f"{name}/{snap}", outcome="ok", reversible=True)
        return f"Snapshot '{snap}' created for {name}."

    if not snap_name:
        return f"snap_name is required for action '{action}'."

    if action == "rollback":
        api.post(f"{base}/{snap_name}/rollback")
        audit.log("snapshot.rollback", f"{name}/{snap_name}", outcome="ok", reversible=False)
        return (f"[ROLLBACK] {name} restored to '{snap_name}'. "
                f"VM may need to be started — check status with manage_vm(status).")

    if action == "delete":
        api.delete(f"{base}/{snap_name}")
        audit.log("snapshot.delete", f"{name}/{snap_name}", outcome="ok", reversible=False)
        return f"Snapshot '{snap_name}' deleted from {name}."

    return f"Unknown action '{action}'."
