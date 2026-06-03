"""
Inventory tool — LLM-callable wrapper around inventory.collect().
"""
from tools import tool
from proxmox_api import ProxmoxAPI
from ssh_client import SSHClient
import inventory


@tool(
    name="get_inventory",
    description="Full node snapshot: VMs, LXCs, storage, disk, failed services.",
    input_schema={
        "type": "object",
        "properties": {
            "node": {
                "type": "string",
                "description": "PVE node name (default: pve)",
            }
        },
        "required": [],
    },
)
def get_inventory(node: str = "pve") -> str:
    api = ProxmoxAPI()
    api.login()
    with SSHClient() as ssh:
        snap = inventory.collect(api, ssh, node=node)
    return inventory.render(snap)
