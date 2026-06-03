"""
Loads configuration from .env in the same directory (or from real env vars).
"""
import os

def _load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

_load_env()

def _e(key, default=""):
    return os.environ.get(key, default)

# ── Proxmox host ───────────────────────────────────────────────────────────────
PROXMOX_HOST = _e("PROXMOX_HOST", "192.168.0.91")
PROXMOX_PORT = int(_e("PROXMOX_PORT", "8006"))
PROXMOX_USER = _e("PROXMOX_USER", "root@pam")
PROXMOX_PASS = _e("PROXMOX_PASS", "")

# ── SSH to PVE host ────────────────────────────────────────────────────────────
SSH_HOST      = _e("SSH_HOST", PROXMOX_HOST)
SSH_PORT      = int(_e("SSH_PORT", "22"))
SSH_USER      = _e("SSH_USER", "root")
SSH_KEYS_DIR  = _e("SSH_KEYS_DIR", r"D:\SSH Keys")
SSH_KEY       = _e("SSH_KEY", "proxmox_id_ed25519")    # filename inside SSH_KEYS_DIR

def ssh_key_path(key_filename: str) -> str:
    return os.path.join(SSH_KEYS_DIR, key_filename)

def pve_key_path() -> str:
    return ssh_key_path(SSH_KEY)

# ── Guest connection map  (name → {ip, key_file, user}) ───────────────────────
def guest_connections() -> dict:
    """Build a {guest_name: {ip, key_path, user}} map from env vars."""
    guests = {}
    prefix_ip  = "GUEST_IP_"
    prefix_key = "GUEST_KEY_"
    for k, v in os.environ.items():
        if k.startswith(prefix_ip):
            name = k[len(prefix_ip):]
            key_file = os.environ.get(prefix_key + name, "")
            guests[name] = {
                "ip":       v,
                "key_path": ssh_key_path(key_file) if key_file else "",
                "user":     "root",
            }
    return guests

# ── Backup / storage ───────────────────────────────────────────────────────────
BACKUP_STORAGE   = _e("BACKUP_STORAGE",   "local-pbs")
BACKUP_MAX_AGE_H = int(_e("BACKUP_MAX_AGE_H", "24"))
STORAGE_WARN_PCT = int(_e("STORAGE_WARN_PCT",  "80"))

# ── KPI / audit ────────────────────────────────────────────────────────────────
KPI_WINDOW_DAYS   = 7
AUDIT_LOG_PATH    = os.path.expanduser("~/.proxmox-agent/audit.jsonl")
AUDIT_FLUSH_EVERY = 50

# ── RPO targets by guest tag ───────────────────────────────────────────────────
RPO_TAGS = {"prod": 4, "dev": 24, "archive": 168}
