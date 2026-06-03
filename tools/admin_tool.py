"""
Administrative tools — container creation, task log, node info.
"""
import datetime
import audit
from tools import tool
from proxmox_api import ProxmoxAPI


def _next_free_vmid(api: ProxmoxAPI) -> int:
    """Ask PVE for the next available VMID."""
    try:
        result = api.get("/cluster/nextid")
        return int(result)
    except Exception:
        return 200


def _list_templates(api: ProxmoxAPI, node: str, storage: str = "") -> list[dict]:
    """Return available LXC OS templates from storage."""
    results = []
    try:
        storages = [storage] if storage else [
            s["storage"] for s in api.get(f"/nodes/{node}/storage")
            if s.get("content", "").find("vztmpl") != -1
        ]
        for st in storages:
            try:
                items = api.get(f"/nodes/{node}/storage/{st}/content?content=vztmpl")
                for item in items:
                    results.append({
                        "volid": item["volid"],
                        "name":  item["volid"].split("/")[-1],
                        "size":  item.get("size", 0),
                    })
            except Exception:
                pass
    except Exception:
        pass
    return results


@tool(
    name="create_container",
    description=(
        "Create a new LXC container on the Proxmox node. "
        "If no template is given, lists available templates first. "
        "Always dry-run by default — set dry_run=false to actually create."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name":     {"type": "string",  "description": "Hostname for the new container."},
            "template": {"type": "string",  "description": "OS template volid (e.g. local:vztmpl/debian-12-standard_12.2-1_amd64.tar.zst). Omit to list available templates."},
            "cores":    {"type": "integer", "description": "vCPU count (default 1)."},
            "memory":   {"type": "integer", "description": "RAM in MB (default 512)."},
            "disk":     {"type": "integer", "description": "Root disk size in GB (default 8)."},
            "storage":  {"type": "string",  "description": "Storage pool for rootfs (default: local-lvm)."},
            "node":     {"type": "string",  "description": "PVE node (default: pve)."},
            "dry_run":  {"type": "boolean", "description": "Simulate only — show the command without running (default true)."},
        },
        "required": ["name"],
    },
)
def create_container(
    name: str,
    template: str = "",
    cores: int = 1,
    memory: int = 512,
    disk: int = 8,
    storage: str = "local-lvm",
    node: str = "pve",
    dry_run: bool = True,
) -> str:
    api = ProxmoxAPI(); api.login()

    if not template:
        templates = _list_templates(api, node)
        if not templates:
            return "No LXC templates found. Download one via: pveam update && pveam available | grep debian"
        lines = ["Available templates (pass one as 'template' parameter):"]
        for t in templates[:15]:
            lines.append(f"  {t['volid']}")
        return "\n".join(lines)

    vmid = _next_free_vmid(api)
    config = {
        "vmid":       vmid,
        "ostemplate": template,
        "hostname":   name,
        "cores":      cores,
        "memory":     memory,
        "rootfs":     f"{storage}:{disk}",
        "net0":       "name=eth0,bridge=vmbr0,ip=dhcp",
        "unprivileged": 1,
        "start":      1,
    }

    if dry_run:
        lines = [f"[DRY RUN] Would create LXC {name} (VMID {vmid}) on {node}:"]
        for k, v in config.items():
            lines.append(f"  {k}: {v}")
        lines.append("\nPass dry_run=false to execute.")
        return "\n".join(lines)

    api.post(f"/nodes/{node}/lxc", config)
    audit.log("container.create", f"{name} ({vmid})", outcome="ok", reversible=False)
    return f"Container **{name}** created (VMID {vmid}) on {node}. Starting…"


@tool(
    name="get_tasks",
    description="Show recent Proxmox task history: backups, migrations, snapshot jobs, updates. Useful for seeing what ran and whether it succeeded.",
    input_schema={
        "type": "object",
        "properties": {
            "hours":  {"type": "integer", "description": "How many hours back to look (default 24)."},
            "filter": {"type": "string",  "description": "Filter by type keyword: backup, snapshot, qmstart, qmstop, etc. Empty = all."},
            "node":   {"type": "string",  "description": "PVE node (default: pve)."},
        },
        "required": [],
    },
)
def get_tasks(hours: int = 24, filter: str = "", node: str = "pve") -> str:
    api = ProxmoxAPI(); api.login()

    try:
        tasks = api.get(f"/nodes/{node}/tasks?limit=100&start=0") or []
    except Exception as exc:
        return f"Could not fetch tasks: {exc}"

    cutoff = datetime.datetime.now().timestamp() - hours * 3600
    recent = [
        t for t in tasks
        if t.get("starttime", 0) >= cutoff
        and (not filter or filter.lower() in t.get("type", "").lower())
    ]

    if not recent:
        return f"No tasks in the last {hours}h" + (f" matching '{filter}'" if filter else "") + "."

    lines = [f"Recent tasks on {node} (last {hours}h):\n",
             "| Time | Type | Target | Status | Duration |",
             "|---|---|---|---|---|"]
    for t in recent[:30]:
        ts   = datetime.datetime.fromtimestamp(t.get("starttime", 0)).strftime("%m-%d %H:%M")
        typ  = t.get("type", "?")
        tgt  = t.get("id", t.get("node", "?"))
        st   = t.get("status", t.get("exitstatus", "running"))
        dur  = ""
        if t.get("endtime") and t.get("starttime"):
            secs = int(t["endtime"] - t["starttime"])
            dur = f"{secs//60}m{secs%60}s" if secs >= 60 else f"{secs}s"
        ok = "✓" if st == "OK" else ("…" if st == "running" else "✗")
        lines.append(f"| {ts} | {typ} | {tgt} | {ok} {st} | {dur} |")

    return "\n".join(lines)
