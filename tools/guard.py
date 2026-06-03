"""
Safety guards — prevent destructive changes to the Proxmox host itself.
All tools that touch the host (apply_patches on node, firewall changes, etc.)
call guard.check() first.
"""
import os
import audit


# Protected targets that require explicit override
PROTECTED_TARGETS = set(os.environ.get("PROTECTED_TARGETS", "pve localhost").split())


def is_protected(target: str) -> bool:
    """Return True if target is the Proxmox host and protected."""
    return target.lower() in PROTECTED_TARGETS


def check_host_safety(operation: str, target: str) -> tuple[bool, str]:
    """
    Check if an operation on target is safe to proceed.
    Returns (safe, reason).
    """
    if not is_protected(target):
        return True, ""

    pve_protection = os.environ.get("PVE_PROTECTION_MODE", "strict").lower()

    if pve_protection == "strict":
        audit.log(f"{operation}.blocked", target, outcome="blocked by PVE protection", reversible=True)
        return False, (
            f"🔒 **PVE Protection enabled**: cannot {operation} on the Proxmox host. "
            f"Set `PVE_PROTECTION_MODE=warn` to allow with confirmation, or "
            f"remove 'pve' from `PROTECTED_TARGETS` to disable protection entirely."
        )

    if pve_protection == "warn":
        audit.log(f"{operation}.warn", target, outcome="warned - proceeding", reversible=True)
        return True, (
            f"⚠️ **High-risk operation**: you are modifying the Proxmox host ({target}). "
            f"An incremental backup will be taken first. Proceed with caution."
        )

    return True, ""


async def pre_flight_backup(loop, node: str = "pve") -> tuple[str, str | None]:
    """
    Take an incremental PBS backup of the host config before a risky change.
    Returns (status_message, error_if_any).
    Meant to be awaited in the SSE stream.
    """
    from proxmox_api import ProxmoxAPI
    import time

    api = ProxmoxAPI(); api.login()
    storage = os.environ.get("BACKUP_STORAGE", "local-pbs")

    try:
        # Backup the host's config files as a pseudo-guest via vzdump
        # (or just the PVE system state)
        upid = api.post(f"/nodes/{node}/vzdump", {
            "node":           node,
            "compress":       "zstd",
            "storage":        storage,
            "notes-template": "PVE host protection backup before risky change",
            "exclude-path":   "/proc,/sys,/tmp",
        })

        # Poll for completion
        for _ in range(60):
            time.sleep(2)
            try:
                st = api.get(f"/nodes/{node}/tasks/{str(upid)}/status")
                if st.get("status") == "stopped":
                    ok = st.get("exitstatus") == "OK"
                    if ok:
                        audit.log("host.pre_flight_backup", node, outcome="ok", reversible=True)
                        return f"✓ PVE backup completed to {storage}", None
                    return None, f"Backup failed: {st.get('exitstatus')}"
            except Exception:
                pass

        audit.log("host.pre_flight_backup", node, outcome="timeout", reversible=True)
        return None, "Backup timeout — proceeding anyway (backup may still be running)"

    except Exception as exc:
        audit.log("host.pre_flight_backup", node, outcome=f"error: {exc}", reversible=True)
        return None, f"Backup failed: {exc}"


def explain_protection() -> str:
    """Return a human-readable explanation of current protection settings."""
    mode = os.environ.get("PVE_PROTECTION_MODE", "strict").lower()
    targets = PROTECTED_TARGETS
    return (
        f"**PVE Protection Settings**\n\n"
        f"Mode: `{mode}`\n"
        f"Protected targets: {', '.join(sorted(targets)) or 'none'}\n\n"
        f"**Behavior:**\n"
        f"- `strict`: Block all writes to protected targets (current: {'enabled' if mode == 'strict' else 'disabled'})\n"
        f"- `warn`: Allow with pre-flight backup & confirmation (current: {'enabled' if mode == 'warn' else 'disabled'})\n"
        f"- `off`: No protection (use only on dev nodes)\n\n"
        f"**To change:**\n"
        f"```bash\n"
        f"export PVE_PROTECTION_MODE=warn  # or 'strict' or 'off'\n"
        f"export PROTECTED_TARGETS='pve localhost 192.168.1.10'  # space-separated\n"
        f"```"
    )
