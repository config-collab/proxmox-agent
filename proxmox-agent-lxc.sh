#!/bin/bash
##############################################################################
# Proxmox Management Agent — LXC/Container Installer
#
# Installs the autonomous decision-support agent in an unprivileged LXC
# on a Proxmox host, with full API access to the node.
#
# Usage: bash <(curl -fsSL https://raw.githubusercontent.com/your-repo/proxmox-agent/main/proxmox-agent-lxc.sh)
#
# Features:
#   - Minimal footprint (150MB unprivileged LXC)
#   - SSH-free: agent runs in container, makes API calls to Proxmox host
#   - Systemd service: auto-start on boot, managed lifecycle
#   - Prometheus metrics: exposes agent performance
#   - Daily automated scans: cron-driven patch/backup checks
#
# Environment:
#   - Node IP: 192.168.0.91 (auto-detected)
#   - Container storage: local-lvm (configurable)
#   - Network: DHCP on vmbr0 (configurable)
#   - Credentials: Proxmox API token in /etc/proxmox-agent/.env
##############################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
AGENT_HOSTNAME="proxmox-agent"
AGENT_VMID=${AGENT_VMID:-}  # Auto-find if empty
AGENT_STORAGE=${AGENT_STORAGE:-local-lvm}
AGENT_MEMORY=${AGENT_MEMORY:-2048}
AGENT_DISK=${AGENT_DISK:-10}
NODE=${NODE:-$(hostname)}
PVE_HOST=${PVE_HOST:-$(hostname -I | awk '{print $1}')}

##############################################################################
# Utilities
##############################################################################

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

ensure_cmd() {
  command -v "$1" >/dev/null 2>&1 || { log_err "$1 not found. Install and retry."; exit 1; }
}

##############################################################################
# Pre-flight checks
##############################################################################

preflight() {
  log_info "Proxmox Agent LXC Installer"
  log_info "Running pre-flight checks..."

  # Root check
  [ "$EUID" -eq 0 ] || { log_err "Must run as root"; exit 1; }

  # Proxmox check
  ensure_cmd pveversion
  PVE_VERSION=$(pveversion | head -1 | awk '{print $2}')
  log_info "Detected Proxmox VE $PVE_VERSION"

  # Find free VMID
  if [ -z "$AGENT_VMID" ]; then
    AGENT_VMID=$(pvesh get /cluster/nextid)
    log_info "Auto-assigned VMID: $AGENT_VMID"
  fi

  # Storage check
  pvesh get "/storage/$AGENT_STORAGE" >/dev/null || \
    { log_err "Storage '$AGENT_STORAGE' not found"; exit 1; }
  log_info "Storage: $AGENT_STORAGE"
}

##############################################################################
# Create LXC container
##############################################################################

create_container() {
  log_info "Creating unprivileged LXC container..."

  # Use debian-12-standard (minimal, ~150MB)
  TEMPLATE="local:vztmpl/debian-12-standard_12.2-1_amd64.tar.zst"

  # Check if template exists
  pvesh get /nodes/$NODE/storage/$AGENT_STORAGE/content \
    | grep -q "debian-12-standard" || \
    { log_warn "Template not found. Run: pveam update && pveam available"; return 1; }

  # Create container
  pvesh create /nodes/$NODE/lxc \
    -vmid "$AGENT_VMID" \
    -hostname "$AGENT_HOSTNAME" \
    -ostemplate "$TEMPLATE" \
    -storage "$AGENT_STORAGE" \
    -memory "$AGENT_MEMORY" \
    -swap 512 \
    -cores 2 \
    -rootfs "${AGENT_STORAGE}:${AGENT_DISK}" \
    -net0 "name=eth0,bridge=vmbr0,ip=dhcp" \
    -start 1 \
    -unprivileged 1 \
    -description "Proxmox Management Agent"

  log_info "Container created: $AGENT_VMID ($AGENT_HOSTNAME)"
}

##############################################################################
# Install agent inside container
##############################################################################

install_agent() {
  log_info "Installing agent inside container..."

  # Wait for container to start
  for i in {1..30}; do
    pct status "$AGENT_VMID" 2>/dev/null | grep -q "running" && break
    sleep 1
  done

  # Bootstrap Python + dependencies
  pct exec "$AGENT_VMID" -- bash -c '
    set -e
    apt-get update
    apt-get install -y python3 python3-pip python3-venv git curl openssh-client
    mkdir -p /opt/proxmox-agent
  '

  # Clone the agent repo (or copy from here)
  pct exec "$AGENT_VMID" -- git clone \
    https://github.com/your-repo/proxmox-agent.git \
    /opt/proxmox-agent || \
    { log_warn "Git clone failed. Trying direct copy...";
      pct push "$AGENT_VMID" . /opt/proxmox-agent; }

  # Install Python dependencies
  pct exec "$AGENT_VMID" -- python3 -m venv /opt/proxmox-agent/venv
  pct exec "$AGENT_VMID" -- /opt/proxmox-agent/venv/bin/pip install -q -r \
    /opt/proxmox-agent/requirements.txt

  log_info "Agent installed in container"
}

##############################################################################
# Configure API credentials
##############################################################################

configure_api() {
  log_info "Configuring Proxmox API access..."

  log_warn "Next step: Create an API token on the Proxmox host:"
  log_warn "  Datacenter → Permissions → API Tokens → Add"
  log_warn "  User: root@pam"
  log_warn "  Token ID: agent"
  log_warn "  Save the secret (shown once!)"
  log_warn ""
  read -p "Enter the API token (user@realm!id=secret): " API_TOKEN

  # Store credentials in container
  pct push "$AGENT_VMID" /dev/stdin /etc/proxmox-agent/.env <<EOF
PROXMOX_HOST=$PVE_HOST
PROXMOX_API_TOKEN=$API_TOKEN
AGENT_AUTONOMY=1
PVE_PROTECTION_MODE=strict
PRE_CHANGE_BACKUP=snapshot
EOF

  log_info "API credentials stored in container"
}

##############################################################################
# Install systemd service
##############################################################################

install_service() {
  log_info "Installing systemd service..."

  pct push "$AGENT_VMID" /dev/stdin /etc/systemd/system/proxmox-agent-web.service <<'EOF'
[Unit]
Description=Proxmox Management Agent Web UI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/proxmox-agent
Environment="PATH=/opt/proxmox-agent/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/etc/proxmox-agent/.env
ExecStart=/opt/proxmox-agent/venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

  pct exec "$AGENT_VMID" -- systemctl daemon-reload
  pct exec "$AGENT_VMID" -- systemctl enable proxmox-agent-web
  pct exec "$AGENT_VMID" -- systemctl start proxmox-agent-web

  log_info "Service installed and started"
}

##############################################################################
# Install cron jobs
##############################################################################

install_cron() {
  log_info "Installing daily maintenance cron jobs..."

  pct push "$AGENT_VMID" /dev/stdin /etc/cron.d/proxmox-agent <<'EOF'
# Proxmox Agent maintenance

# 2am: Inventory scan + patch check
0 2 * * * root cd /opt/proxmox-agent && \
  /opt/proxmox-agent/venv/bin/python3 -c \
  "import main; main.run_headless('pve')" > /var/log/proxmox-agent-inventory.log 2>&1

# 3am: Security audit
0 3 * * 0 root cd /opt/proxmox-agent && \
  /opt/proxmox-agent/venv/bin/python3 -c \
  "import tools; print(tools.dispatch('security_audit', {}))" \
  > /var/log/proxmox-agent-security.log 2>&1

# 4am: Backup health check
0 4 * * 0 root cd /opt/proxmox-agent && \
  /opt/proxmox-agent/venv/bin/python3 -c \
  "import tools; print(tools.dispatch('check_backups', {}))" \
  > /var/log/proxmox-agent-backups.log 2>&1
EOF

  log_info "Cron jobs configured"
}

##############################################################################
# Print summary
##############################################################################

print_summary() {
  CONTAINER_IP=$(pct exec "$AGENT_VMID" -- hostname -I | awk '{print $1}')

  echo ""
  echo "=========================================="
  echo "✓ Proxmox Agent installed successfully!"
  echo "=========================================="
  echo ""
  echo "Access the web UI:"
  echo "  http://$CONTAINER_IP:8080"
  echo ""
  echo "Container details:"
  echo "  VMID: $AGENT_VMID"
  echo "  Hostname: $AGENT_HOSTNAME"
  echo "  IP: $CONTAINER_IP (DHCP)"
  echo "  Storage: $AGENT_STORAGE"
  echo ""
  echo "Logs:"
  echo "  systemd:  pct exec $AGENT_VMID -- journalctl -u proxmox-agent-web -f"
  echo "  inventory: pct exec $AGENT_VMID -- tail -f /var/log/proxmox-agent-inventory.log"
  echo "  security: pct exec $AGENT_VMID -- tail -f /var/log/proxmox-agent-security.log"
  echo ""
  echo "Next steps:"
  echo "  1. Open http://$CONTAINER_IP:8080 in your browser"
  echo "  2. Configure settings (autonomy level, API token, etc.)"
  echo "  3. Run your first health check"
  echo "  4. Review SECURITY_LEVELS.md for recommended configurations"
  echo ""
  echo "Documentation:"
  echo "  Security: pct exec $AGENT_VMID -- cat /opt/proxmox-agent/SECURITY_LEVELS.md"
  echo ""
}

##############################################################################
# Main
##############################################################################

main() {
  preflight
  create_container
  sleep 5  # Let container stabilize
  install_agent
  configure_api
  install_service
  install_cron
  print_summary
}

main "$@"
