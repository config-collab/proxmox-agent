"""
Backup tools — LLM-callable wrappers around backup.py and pbs.py.
"""
import os
import time
import audit
import backup
import config
import pbs
from tools import tool
from proxmox_api import ProxmoxAPI
from ssh_client import SSHClient


@tool(
    name="check_backups",
    description="Backup status per guest: last backup age, scheduled job coverage, storage fill. Flags missing/overdue.",
    input_schema={
        "type": "object",
        "properties": {
            "node": {"type": "string", "description": "PVE node (default: pve)."},
            "guest_name": {"type": "string", "description": "Single guest name. Omit = all."},
        },
        "required": [],
    },
)
def check_backups(node: str = "pve", guest_name: str = "") -> str:
    api = ProxmoxAPI()
    api.login()

    report = backup.collect(api, node=node)
    audit.log("backup.check", node, outcome="ok", reversible=True)

    if guest_name:
        report.guests = [g for g in report.guests if g.name == guest_name]
        if not report.guests:
            return f"No guest found with name {guest_name!r}."

    return backup.render(report)


@tool(
    name="check_pbs",
    description="PBS deep check (192.168.0.244): datastore usage, snapshot verification, GC/prune task log, disk health.",
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def check_pbs() -> str:
    report = pbs.collect()
    audit.log("pbs.check", pbs.PBS_HOST, outcome="ok" if report.reachable else "error", reversible=True)

    result = pbs.render(report)

    # Append a cross-reference with PVE backup ages if PBS is reachable
    if report.reachable:
        unverified_guests = []
        for ds in report.datastores:
            for snaps in _group_by_guest(ds.snapshots).values():
                latest = snaps[0]
                if latest.verified is False:
                    unverified_guests.append(f"{latest.backup_type}/{latest.backup_id}")
        if unverified_guests:
            result += (
                f"\n\n> **Action required:** run a PBS verify job for: "
                + ", ".join(unverified_guests)
            )

    return result


def _group_by_guest(snapshots: list) -> dict:
    groups: dict = {}
    for s in snapshots:
        key = f"{s.backup_type}/{s.backup_id}"
        groups.setdefault(key, []).append(s)
    return groups


@tool(
    name="run_backup_now",
    description=(
        "Trigger an immediate on-demand backup of a VM or LXC to PBS/storage. "
        "Use before risky changes or when the cron schedule isn't enough. "
        "Polls until the backup job completes (max ~10 min)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name":    {"type": "string", "description": "VM or container name."},
            "node":    {"type": "string", "description": "PVE node (default: pve)."},
            "storage": {"type": "string", "description": "Backup storage target (default: from .env BACKUP_STORAGE)."},
        },
        "required": ["name"],
    },
)
def run_backup_now(name: str, node: str = "pve", storage: str = "") -> str:
    from tools.vm_tool import _find_guest
    api = ProxmoxAPI(); api.login()
    vmid, gtype = _find_guest(api, node, name)
    if vmid is None:
        return f"'{name}' not found on {node}."

    bk_storage = storage or config.BACKUP_STORAGE
    upid = api.post(f"/nodes/{node}/vzdump", {
        "vmid":            str(vmid),
        "mode":            "snapshot",
        "compress":        "zstd",
        "storage":         bk_storage,
        "notes-template":  "on-demand via proxmox-agent",
    })
    audit.log("backup.run_now", f"{name} ({vmid})", outcome="started", reversible=True)

    upid_str = str(upid)
    for _ in range(120):   # poll up to 10 min
        time.sleep(5)
        try:
            st = api.get(f"/nodes/{node}/tasks/{upid_str}/status")
            if st.get("status") == "stopped":
                ok = st.get("exitstatus") == "OK"
                audit.log("backup.run_now", f"{name} ({vmid})",
                          outcome="ok" if ok else "error", reversible=True)
                if ok:
                    return f"Backup of **{name}** completed to `{bk_storage}`."
                return f"Backup failed: {st.get('exitstatus', 'unknown error')}"
        except Exception:
            pass

    return f"Backup of {name} started (UPID: {upid_str[:40]}). May still be running — check PBS."


@tool(
    name="pbs_maintenance",
    description=(
        "Run garbage collection or verify on the Proxmox Backup Server. "
        "GC reclaims space from deleted/pruned snapshots. "
        "Verify checks integrity of all stored backups. Both are safe read-mostly operations."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action":    {"type": "string", "enum": ["gc", "verify", "status"],
                          "description": "gc=garbage collect, verify=check integrity, status=show datastore info."},
            "datastore": {"type": "string", "description": "PBS datastore name (default: from PBS_DATASTORE env or first available)."},
        },
        "required": ["action"],
    },
)
def pbs_maintenance(action: str = "gc", datastore: str = "") -> str:
    pbs_host    = os.environ.get("PBS_HOST", pbs.PBS_HOST)
    pbs_keyfile = os.environ.get("PBS_KEY_FILE", "pbs_id_ed25519")
    key_path    = config.ssh_key_path(pbs_keyfile)

    try:
        ssh = SSHClient(host=pbs_host, user="root", key_path=key_path)
        ssh.connect()
    except Exception as exc:
        return f"Cannot connect to PBS at {pbs_host}: {exc}"

    # Discover datastore name if not given
    if not datastore:
        out, _, _ = ssh.run("proxmox-backup-manager datastore list --output-format json", check=False)
        try:
            import json
            ds_list = json.loads(out)
            datastore = ds_list[0].get("name", "pbs-main") if ds_list else "pbs-main"
        except Exception:
            datastore = os.environ.get("PBS_DATASTORE", "pbs-main")

    cmd_map = {
        "gc":     f"proxmox-backup-manager garbage-collection start {datastore}",
        "verify": f"proxmox-backup-manager verify start {datastore}",
        "status": f"proxmox-backup-manager datastore show {datastore} --output-format json",
    }
    cmd = cmd_map.get(action)
    if not cmd:
        ssh.close(); return f"Unknown action '{action}'."

    out, err, rc = ssh.run(cmd, check=False, timeout=600)
    ssh.close()

    audit.log(f"pbs.{action}", datastore, outcome="ok" if rc == 0 else "error", reversible=True)
    result = (out or err or "").strip()

    if action == "status":
        try:
            import json
            d = json.loads(result)
            used = d.get("used", 0); total = d.get("total", 1)
            pct  = round(used / total * 100, 1) if total else 0
            gb   = lambda b: f"{b/1024**3:.1f}GB"
            return f"PBS datastore **{datastore}**: {gb(used)} used / {gb(total)} total ({pct}%)"
        except Exception:
            pass

    prefix = {"gc": "Garbage collection", "verify": "Verify"}.get(action, action)
    return f"{prefix} started on `{datastore}`.\n```\n{result[:800]}\n```" if result else f"{prefix} triggered on `{datastore}`."
