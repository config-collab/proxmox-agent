#!/bin/bash
# Proxmox Agent Deployment Script for BananaPi / Raspberry Pi
# Usage: bash deploy.sh

set -e

echo "=== Proxmox Agent Deployment ==="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 not found. Install: sudo apt install python3${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Python3 found: $(python3 --version)"

# Check Git
if ! command -v git &> /dev/null; then
    echo -e "${RED}❌ Git not found. Install: sudo apt install git${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Git found"

# Setup directory
AGENT_DIR="$HOME/.proxmox-agent"
mkdir -p "$AGENT_DIR"
cd "$AGENT_DIR"

echo ""
echo "=== Cloning Repository ==="

# Clone or update repo
if [ -d ".git" ]; then
    echo "Updating existing repository..."
    git pull origin master
else
    echo "Cloning repository..."
    git clone https://github.com/config-collab/proxmox-agent.git .
fi

echo -e "${GREEN}✓${NC} Repository ready"

# Create .env if not exists
echo ""
echo "=== Configuration ==="

if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cat > .env << 'EOF'
# Proxmox Configuration
PROXMOX_HOST=192.168.1.10
PROXMOX_API_TOKEN=PVEAPIToken=user@realm!tokenid=token-value
SSH_USER=root
SSH_KEY_PATH=~/.ssh/proxmox_id_ed25519

# PBS (Proxmox Backup Server)
PBS_HOST=192.168.0.244

# LLM Provider
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Daemon (BETA)
DAEMON_ENABLED=0
NTFY_URL=https://ntfy.sh/my-proxmox-alerts
DAEMON_CHECK_INTERVAL=60
DAEMON_ALERT_THRESHOLD_DISK=85

# Agent Security
AGENT_AUTONOMY=1
PVE_PROTECTION_MODE=strict
PRE_CHANGE_BACKUP=snapshot
EOF

    echo -e "${YELLOW}⚠ Created .env with defaults${NC}"
    echo "❗ IMPORTANT: Edit .env and set:"
    echo "   - PROXMOX_HOST (your Proxmox IP)"
    echo "   - PROXMOX_API_TOKEN (from Proxmox)"
    echo "   - ANTHROPIC_API_KEY (from console.anthropic.com)"
    echo "   - NTFY_URL (your ntfy.sh channel, optional)"
    echo ""
    echo "   nano $AGENT_DIR/.env"
else
    echo -e "${GREEN}✓${NC} .env already exists"
fi

# Install Python dependencies
echo ""
echo "=== Installing Dependencies ==="

if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing packages..."
pip install -q --upgrade pip setuptools wheel

if [ -f "requirements.txt" ]; then
    pip install -q -r requirements.txt
else
    # Core dependencies
    pip install -q \
        fastapi \
        uvicorn \
        anthropic \
        pydantic \
        python-dotenv \
        paramiko \
        requests
fi

echo -e "${GREEN}✓${NC} Dependencies installed"

# Setup systemd service for daemon (optional)
echo ""
echo "=== Daemon Setup (Optional) ==="

if [ -f "daemon.py" ]; then
    read -p "Install daemon as systemd service? (y/n) " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Create systemd service file
        SERVICE_FILE="/tmp/proxmox-daemon.service"
        cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Proxmox Agent Daemon (BETA)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=$USER
WorkingDirectory=$AGENT_DIR
ExecStart=$(which python3) $AGENT_DIR/daemon.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=proxmox-daemon

[Install]
WantedBy=multi-user.target
EOF

        echo "Installing systemd service (requires sudo)..."
        sudo cp "$SERVICE_FILE" /etc/systemd/system/proxmox-daemon.service
        sudo systemctl daemon-reload
        sudo systemctl enable proxmox-daemon

        echo -e "${GREEN}✓${NC} Systemd service installed"
        echo ""
        echo "Start daemon with:"
        echo "  sudo systemctl start proxmox-daemon"
        echo ""
        echo "View logs with:"
        echo "  sudo journalctl -u proxmox-daemon -f"
    fi
fi

# Test daemon (optional)
echo ""
echo "=== Testing ==="

read -p "Test daemon now? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ -f "daemon.py" ]; then
        echo "Running daemon test..."
        python3 daemon.py --once
        echo -e "${GREEN}✓${NC} Daemon test complete"
    fi
fi

# Summary
echo ""
echo "=== ✅ Deployment Complete ==="
echo ""
echo "Next steps:"
echo ""
echo "1. Edit configuration:"
echo "   nano $AGENT_DIR/.env"
echo ""
echo "2. Test daemon (if not tested above):"
echo "   cd $AGENT_DIR"
echo "   source venv/bin/activate"
echo "   python3 daemon.py --once"
echo ""
echo "3. Start daemon:"
echo "   sudo systemctl start proxmox-daemon"
echo ""
echo "4. View logs:"
echo "   sudo journalctl -u proxmox-daemon -f"
echo ""
echo "5. Start web UI (interactive):"
echo "   cd $AGENT_DIR"
echo "   source venv/bin/activate"
echo "   python3 -m uvicorn server:app --host 0.0.0.0 --port 8080"
echo ""
echo "Then open: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
