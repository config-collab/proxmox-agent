"""
Proxmox REST API wrapper.
Authenticates once per session, caches the ticket, reuses it.
"""
import os
import urllib.request
import urllib.parse
import urllib.error
import json
import ssl
import config

# Ignore self-signed cert on PVE web UI (default install)
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


class ProxmoxAPI:
    def __init__(self):
        self._base   = f"https://{config.PROXMOX_HOST}:{config.PROXMOX_PORT}/api2/json"
        self._ticket = None
        self._csrf   = None
        self._token  = os.environ.get("PROXMOX_API_TOKEN", "")  # user@realm!id=secret

    # ── Authentication ─────────────────────────────────────────────────────────

    def login(self):
        if self._token:
            return self   # API token needs no login handshake
        data = urllib.parse.urlencode({
            "username": config.PROXMOX_USER,
            "password": config.PROXMOX_PASS,
        }).encode()
        req = urllib.request.Request(
            f"{self._base}/access/ticket",
            data=data,
            method="POST",
        )
        with urllib.request.urlopen(req, context=_CTX, timeout=15) as resp:
            body = json.loads(resp.read())
        self._ticket = body["data"]["ticket"]
        self._csrf   = body["data"]["CSRFPreventionToken"]
        return self

    # ── Core request ───────────────────────────────────────────────────────────

    def _request(self, method, path, data=None):
        url = f"{self._base}{path}"
        if self._token:
            headers = {"Authorization": f"PVEAPIToken={self._token}"}
        else:
            headers = {
                "Cookie": f"PVEAuthCookie={self._ticket}",
                "CSRFPreventionToken": self._csrf,
            }
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=_CTX, timeout=30) as resp:
                return json.loads(resp.read())["data"]
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"PVE API {method} {path} -> {exc.code}: {exc.read().decode()}") from exc

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, data=None):
        return self._request("POST", path, data)

    def delete(self, path):
        return self._request("DELETE", path)

    # ── Convenience helpers ────────────────────────────────────────────────────

    def nodes(self):
        return self.get("/nodes")

    def node_status(self, node="pve"):
        return self.get(f"/nodes/{node}/status")

    def vms(self, node="pve"):
        return self.get(f"/nodes/{node}/qemu")

    def containers(self, node="pve"):
        return self.get(f"/nodes/{node}/lxc")

    def storage(self, node="pve"):
        return self.get(f"/nodes/{node}/storage")

    def version(self):
        return self.get("/version")
