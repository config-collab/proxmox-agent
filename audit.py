"""
Audit log — writes JSONL to ~/.proxmox-agent/audit.jsonl.
Batches writes to reduce flash storage wear (configurable via AUDIT_FLUSH_EVERY).
"""
import json
import os
import datetime
import atexit
import config

_buffer: list[dict] = []
_ops_since_flush: int = 0


def _ensure_dir():
    os.makedirs(os.path.dirname(config.AUDIT_LOG_PATH), exist_ok=True)


def _flush():
    global _buffer, _ops_since_flush
    if not _buffer:
        return
    _ensure_dir()
    with open(config.AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
        for entry in _buffer:
            fh.write(json.dumps(entry) + "\n")
    _buffer = []
    _ops_since_flush = 0


# Flush on clean exit so nothing is lost
atexit.register(_flush)


def log(operation: str, target: str, outcome: str = "ok", reversible: bool = True, **extra):
    """
    Record a state-changing operation.

    operation  — verb, e.g. "vm.stop", "lxc.create", "patch.apply"
    target     — guest ID, storage name, etc.
    outcome    — "ok" | "error" | "dry-run"
    reversible — whether the change can be undone
    """
    global _ops_since_flush
    entry = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "agent": "proxmox-agent",
        "operation": operation,
        "target": str(target),
        "outcome": outcome,
        "reversible": reversible,
        **extra,
    }
    _buffer.append(entry)
    _ops_since_flush += 1

    if _ops_since_flush >= config.AUDIT_FLUSH_EVERY:
        _flush()


def flush():
    """Force an immediate flush — call at session end or before long sleeps."""
    _flush()
