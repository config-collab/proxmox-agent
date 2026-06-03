#!/usr/bin/env bash
# Proxmox Agent — AI-powered management co-pilot
# https://github.com/your-repo/proxmox-agent
#
# This is a community-scripts compatible LXC installer.
# Install by running:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/your-repo/proxmox-agent/main/ct-proxmox-agent.sh)"
#
# Or use the Proxmox Helper Scripts UI:
#   Add this URL to your helper scripts list

set -e

function header_info {
  clear
  cat <<"EOF"
╔═══════════════════════════════════════════════════════════════╗
║                 PROXMOX MANAGEMENT AGENT                      ║
║           Decision-Support AI for Infrastructure             ║
╚═══════════════════════════════════════════════════════════════╝

Deploys a full-stack management assistant in a lightweight LXC:

  • Web UI: FastAPI + vanilla JS dashboard
  • CLI: Interactive chat with 26 tools
  • API: REST endpoints for programmatic access
  • Automation: Cron-driven inventory, patch, backup checks
  • Security: Autonomy levels + PVE protection guards
  • Transparency: Full audit logs + reasoning chains

This is NOT an autonomous agent—it's a decision-support tool
that shows reasoning, requires your approval, and logs everything.

EOF
}

function msg_info() {
  local msg="$1"
  echo -e "\e[32m[INFO]\e[0m $msg"
}

function msg_warn() {
  local msg="$1"
  echo -e "\e[33m[WARN]\e[0m $msg"
}

function msg_error() {
  local msg="$1"
  echo -e "\e[31m[ERROR]\e[0m $msg" >&2
}

function header_info() {
  echo "Proxmox Management Agent Installer"
}

function setting_up_container() {
  msg_info "Setting up container environment..."
}

function install_dependencies() {
  msg_info "Installing dependencies..."
  apt-get update
  apt-get install -y \
    python3 python3-pip python3-venv python3-dev \
    git curl wget openssh-client jq \
    build-essential libssl-dev libffi-dev
}

function clone_repository() {
  msg_info "Cloning Proxmox Agent repository..."
  mkdir -p /opt/proxmox-agent
  cd /opt/proxmox-agent
  git clone https://github.com/your-repo/proxmox-agent.git . || \
    { msg_warn "Git clone failed. Using fallback."; return 1; }
}

function setup_python_env() {
  msg_info "Setting up Python environment..."
  cd /opt/proxmox-agent
  python3 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip setuptools wheel
  pip install -r requirements.txt
}

function configure_api_token() {
  msg_info "Configuring Proxmox API credentials..."

  # Interactive setup
  read -p "Enter Proxmox host IP (default: auto-detect from PVE_HOST env): " PROXMOX_HOST
  PROXMOX_HOST="${PROXMOX_HOST:-${PVE_HOST:-192.168.1.10}}"

  read -p "Enter API token (user@realm!id=secret): " PROXMOX_API_TOKEN

  # Store in env file
  mkdir -p /etc/proxmox-agent
  cat > /etc/proxmox-agent/.env <<EOF
# Proxmox connection
PROXMOX_HOST=$PROXMOX_HOST
PROXMOX_API_TOKEN=$PROXMOX_API_TOKEN

# Agent security settings
AGENT_AUTONOMY=1              # 0=read-only, 1=suggest, 2=maintain, 3=full
PVE_PROTECTION_MODE=strict    # strict, warn, off
PRE_CHANGE_BACKUP=snapshot    # none, snapshot, pbs
PROTECTED_TARGETS=pve localhost

# Backup defaults
BACKUP_STORAGE=local-pbs
PBS_HOST=192.168.1.10

# LLM provider (optional)
LLM_PROVIDER=claude
# ANTHROPIC_API_KEY=sk-...

# Alerts (optional)
NTFY_URL=

# Logging
AUDIT_LOG_PATH=~/.proxmox-agent/audit.jsonl
EOF

  chmod 600 /etc/proxmox-agent/.env
  msg_info "API token configured"
}

function install_systemd_service() {
  msg_info "Installing systemd service..."

  cat > /etc/systemd/system/proxmox-agent-web.service <<'EOF'
[Unit]
Description=Proxmox Management Agent Web Interface
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/proxmox-agent
Environment="PATH=/opt/proxmox-agent/venv/bin:/usr/bin:/bin"
EnvironmentFile=/etc/proxmox-agent/.env
ExecStart=/opt/proxmox-agent/venv/bin/uvicorn server:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=10
StartLimitInterval=60
StartLimitBurst=3

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable proxmox-agent-web
  systemctl start proxmox-agent-web

  msg_info "Service started. Check status: systemctl status proxmox-agent-web"
}

function install_cron_jobs() {
  msg_info "Installing daily maintenance jobs..."

  cat > /etc/cron.d/proxmox-agent <<'EOF'
# Proxmox Agent daily maintenance (UTC times)

# 2:00 AM — Inventory + patch check
0 2 * * * root cd /opt/proxmox-agent && source venv/bin/activate && python3 main.py --no-llm >> /var/log/proxmox-agent-cron.log 2>&1

# 3:00 AM Sunday — Security audit
0 3 * * 0 root cd /opt/proxmox-agent && source venv/bin/activate && python3 -c "import tools; print(tools.dispatch('security_audit', {}))" >> /var/log/proxmox-agent-cron.log 2>&1

# 4:00 AM Sunday — Backup health
0 4 * * 0 root cd /opt/proxmox-agent && source venv/bin/activate && python3 -c "import tools; print(tools.dispatch('check_pbs', {}))" >> /var/log/proxmox-agent-cron.log 2>&1
EOF

  chmod 644 /etc/cron.d/proxmox-agent
  msg_info "Cron jobs configured"
}

function print_info() {
  local CONTAINER_IP=$(hostname -I | awk '{print $1}')

  echo ""
  echo "╔════════════════════════════════════════════════════╗"
  echo "║  ✓ Proxmox Agent installed successfully!           ║"
  echo "╚════════════════════════════════════════════════════╝"
  echo ""
  echo "🌐 Web UI: http://$CONTAINER_IP:8080"
  echo ""
  echo "📋 Configuration:"
  echo "   Token: /etc/proxmox-agent/.env"
  echo "   Logs:  /var/log/proxmox-agent-cron.log"
  echo "   Audit: ~/.proxmox-agent/audit.jsonl"
  echo ""
  echo "📖 Documentation:"
  echo "   Security levels: cat /opt/proxmox-agent/SECURITY_LEVELS.md"
  echo "   Tools list:      python3 -c \"import tools; print(tools.list_all())\" "
  echo ""
  echo "🔍 Verify service:"
  echo "   systemctl status proxmox-agent-web"
  echo "   journalctl -u proxmox-agent-web -f"
  echo ""
  echo "🔐 Security defaults:"
  echo "   • Autonomy: Level 1 (Suggest — you approve actions)"
  echo "   • PVE Protection: Strict (host writes blocked)"
  echo "   • Pre-backup: VM snapshots before changes"
  echo "   • Audit: All operations logged"
  echo ""
  echo "Next: Open http://$CONTAINER_IP:8080 to get started"
  echo ""
}

# Main execution
{
  header_info
  setting_up_container
  install_dependencies
  clone_repository || msg_warn "Git clone failed—make sure you're running in a Proxmox LXC"
  setup_python_env
  configure_api_token
  install_systemd_service
  install_cron_jobs
  print_info
}
