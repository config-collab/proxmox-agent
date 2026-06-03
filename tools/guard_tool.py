"""
Guard status & info tools — check PVE protection, view settings, enable/disable guards.
"""
from tools import tool
from tools import guard


@tool(
    name="check_pve_protection",
    description="Show current PVE (Proxmox host) protection settings. Use before risky host-level changes.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
def check_pve_protection() -> str:
    return guard.explain_protection()


@tool(
    name="test_guard",
    description="Test the PVE guard by attempting a dry-run on the host. Shows whether the operation would be blocked.",
    input_schema={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": "Operation to simulate: 'patch', 'firewall', 'snapshot', etc.",
            },
        },
        "required": ["operation"],
    },
)
def test_guard(operation: str = "patch") -> str:
    safe, reason = guard.check_host_safety(operation, "pve")
    if safe:
        return f"✓ Operation '{operation}' on host would be **allowed**.\n\n{reason or 'No warnings.'}"
    else:
        return f"🔒 Operation '{operation}' on host would be **BLOCKED**.\n\n{reason}"
