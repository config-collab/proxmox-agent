# Deploy to BananaPi / Raspberry Pi

## Quick Deploy (One Command)

Run this on your BananaPi:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/config-collab/proxmox-agent/master/deploy.sh)
```

Or if you have local git:

```bash
git clone https://github.com/config-collab/proxmox-agent.git ~/.proxmox-agent
cd ~/.proxmox-agent
bash deploy.sh
```

## What The Script Does

1. ✅ Checks Python3 and Git
2. ✅ Clones/updates repository
3. ✅ Creates .env file (you edit it)
4. ✅ Creates Python virtual environment
5. ✅ Installs dependencies
6. ✅ Optionally installs systemd service
7. ✅ Optionally tests daemon
8. ✅ Shows next steps

## Manual Deploy (If Script Fails)

### Step 1: SSH to BananaPi
```bash
ssh pi@192.168.x.x  # or banapi@192.168.x.x
```

### Step 2: Clone Repository
```bash
mkdir -p ~/.proxmox-agent
cd ~/.proxmox-agent
git clone https://github.com/config-collab/proxmox-agent.git .
```

### Step 3: Setup Python Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure
```bash
nano .env
# Edit with your Proxmox host, API token, LLM key
```

### Step 5: Test Daemon
```bash
python3 daemon.py --once
```

### Step 6: Start as Service (Optional)
```bash
# Create systemd service
sudo tee /etc/systemd/system/proxmox-daemon.service > /dev/null << 'EOF'
[Unit]
Description=Proxmox Agent Daemon (BETA)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/.proxmox-agent
ExecStart=/home/pi/.proxmox-agent/venv/bin/python3 /home/pi/.proxmox-agent/daemon.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable proxmox-daemon
sudo systemctl start proxmox-daemon

# View logs
sudo journalctl -u proxmox-daemon -f
```

## Configuration Required

Edit `.env`:

```env
# REQUIRED: Your Proxmox host
PROXMOX_HOST=192.168.1.10

# REQUIRED: API token from Proxmox
# Go to Datacenter → Permissions → API Tokens
PROXMOX_API_TOKEN=PVEAPIToken=user@realm!tokenid=value

# REQUIRED: LLM API key
ANTHROPIC_API_KEY=sk-ant-...

# OPTIONAL: SSH key path (if different)
SSH_KEY_PATH=~/.ssh/proxmox_id_ed25519

# OPTIONAL: Daemon settings
DAEMON_ENABLED=1
NTFY_URL=https://ntfy.sh/my-proxmox-alerts

# OPTIONAL: Security settings
AGENT_AUTONOMY=1
PVE_PROTECTION_MODE=strict
PRE_CHANGE_BACKUP=snapshot
```

## Verify Installation

### Check Daemon Status
```bash
sudo systemctl status proxmox-daemon
```

### Check Logs
```bash
sudo journalctl -u proxmox-daemon -n 50
```

### Test Daemon Manually
```bash
cd ~/.proxmox-agent
source venv/bin/activate
python3 daemon.py --once
```

Expected output:
```
[info] Running checks once...
[info] Checking disk capacity...
[info] Checking backup health...
[info] Checking PBS health...
[info] Checking critical services...
[info] All checks completed
```

### Start Web UI (Interactive)
```bash
cd ~/.proxmox-agent
source venv/bin/activate
python3 -m uvicorn server:app --host 0.0.0.0 --port 8080
```

Then open browser: `http://192.168.x.x:8080`

## Troubleshooting

### Python3 not found
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

### Git not found
```bash
sudo apt install git
```

### Permission denied on systemd
Make sure you use `sudo`:
```bash
sudo systemctl start proxmox-daemon
sudo journalctl -u proxmox-daemon -f
```

### SSH key not found
Generate key:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/proxmox_id_ed25519 -C "proxmox-agent"
ssh-copy-id -i ~/.ssh/proxmox_id_ed25519.pub root@192.168.1.10
```

### Daemon not starting
Check logs:
```bash
sudo journalctl -u proxmox-daemon -n 100
```

Check config:
```bash
cat ~/.proxmox-agent/.env | head -5
```

### Can't connect to Proxmox
Test API:
```bash
curl -k https://192.168.1.10:8006/api2/json/version
```

Test SSH:
```bash
ssh -i ~/.ssh/proxmox_id_ed25519 root@192.168.1.10 pveversion
```

## What's Running

After deployment:

- ✅ **Daemon** — Background monitoring (if enabled)
- ✅ **Audit log** — All operations logged to `~/.proxmox-agent/.operations/audit.jsonl`
- ✅ **Web UI** — Optional interactive interface
- ✅ **CLI** — Optional command-line interface

## Next Steps

1. **Monitor daemon**: `sudo journalctl -u proxmox-daemon -f`
2. **Check alerts**: Look for ntfy.sh notifications
3. **Test predictions**: Ask agent about disk capacity
4. **Run health check**: `python3 daemon.py --once`

## Uninstall

```bash
# Stop daemon
sudo systemctl stop proxmox-daemon
sudo systemctl disable proxmox-daemon

# Remove service
sudo rm /etc/systemd/system/proxmox-daemon.service
sudo systemctl daemon-reload

# Remove repository
rm -rf ~/.proxmox-agent
```

---

**Need help?** Check daemon logs or GitHub issues.
