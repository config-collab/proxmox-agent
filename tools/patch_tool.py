"""
Patch tools — LLM-callable wrappers around patch.py.
"""
import config
import audit
import patch
from tools import tool, guard
from proxmox_api import ProxmoxAPI
from ssh_client import SSHClient
import inventory


def _running_guests_with_connections() -> list[dict]:
    """Return running guests that have a known IP + key in .env."""
    api = ProxmoxAPI()
    api.login()
    with SSHClient() as ssh:
        snap = inventory.collect(api, ssh)

    conns = config.guest_connections()
    result = []
    for g in snap.guests:
        if g.status != "running":
            continue
        conn = conns.get(g.name)
        if not conn or not conn["ip"] or not conn["key_path"]:
            continue
        result.append({
            "id":       g.id,
            "name":     g.name,
            "ip":       conn["ip"],
            "key_path": conn["key_path"],
            "user":     conn["user"],
        })
    return result


@tool(
    name="check_patches",
    description="Check pending updates on all running guests. Classifies: security/kernel/routine.",
    input_schema={
        "type": "object",
        "properties": {
            "guest_name": {
                "type": "string",
                "description": "Guest name to check. Omit = all.",
            }
        },
        "required": [],
    },
)
def check_patches(guest_name: str = "") -> str:
    guests = _running_guests_with_connections()

    if guest_name:
        guests = [g for g in guests if g["name"] == guest_name]
        if not guests:
            return f"No running guest found with name {guest_name!r} and known SSH credentials."

    if not guests:
        return "No running guests with known SSH credentials found."

    states: list[patch.GuestPatchState] = []
    for g in guests:
        print(f"  checking {g['name']} ({g['ip']}) ...")
        state = patch.check_guest(
            guest_id=g["id"], guest_name=g["name"],
            ip=g["ip"], key_path=g["key_path"], user=g["user"],
        )
        states.append(state)
        audit.log("patch.check", g["name"], outcome="ok", reversible=True)

    return patch.render_patch_report(states)


@tool(
    name="apply_patches",
    description="Apply updates on a guest. dry_run=true (default) always. Set false only after user confirms. Kernel updates need reboot.",
    input_schema={
        "type": "object",
        "properties": {
            "guest_name": {"type": "string", "description": "Guest name."},
            "security_only": {"type": "boolean", "description": "Security updates only."},
            "dry_run": {"type": "boolean", "description": "Simulate only (default true)."},
        },
        "required": ["guest_name"],
    },
)
def apply_patches(guest_name: str, security_only: bool = False, dry_run: bool = True) -> str:
    # Check if target is the protected host
    safe, reason = guard.check_host_safety("patch", guest_name)
    if not safe:
        return reason

    conns = config.guest_connections()
    conn  = conns.get(guest_name)
    if not conn:
        return f"No SSH connection info for guest {guest_name!r} — check .env GUEST_IP_/GUEST_KEY_ vars."

    result = patch.apply_guest(
        guest_id=0, guest_name=guest_name,
        ip=conn["ip"], key_path=conn["key_path"], user=conn["user"],
        security_only=security_only,
        dry_run=dry_run,
    )

    outcome = "dry-run" if dry_run else "ok"
    audit.log(
        "patch.apply", guest_name,
        outcome=outcome,
        reversible=False,
        security_only=security_only,
        dry_run=dry_run,
    )
    return result
