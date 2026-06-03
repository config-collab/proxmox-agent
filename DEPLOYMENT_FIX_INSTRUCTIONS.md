# Deployment Fix Instructions for BananaPi

## Status
✅ **Fixed code is now on GitHub** (commit d482d08)
⚠️ **BananaPi still running old code** (needs to pull and restart)

## What Was Fixed
The server startup hang was caused by:
1. Heavy modules (inventory, tools, ProxmoxAPI, SSHClient) imported at module level
2. These imports triggered Proxmox API connections at startup → hung waiting for auth
3. Missing `if __name__ == "__main__"` entry point

**Solution:** Lazy-load modules on first use, only import when routes are called.

## How to Deploy the Fix on BananaPi

### Option 1: SSH (Recommended)
```bash
ssh pi@192.168.0.235

# Pull latest code
cd /home/pi/proxmox-agent
git pull origin master

# Kill old server (find the process)
pkill -f "python3 server.py" || true

# Start new server
python3 server.py &

# Verify
curl http://localhost:8080/
# Should return HTML, not "Not Found"
```

### Option 2: Via systemd (If installed as service)
```bash
ssh pi@192.168.0.235
sudo systemctl restart proxmox-agent
sudo journalctl -u proxmox-agent -f    # Watch logs
```

### Option 3: Manual Redeploy
If SSH access is unavailable:
1. Clone the repo locally: `git clone https://github.com/config-collab/proxmox-agent.git`
2. Copy all files to BananaPi via USB or network
3. Kill old process: `ps aux | grep python3`
4. Start new: `python3 server.py &`

---

## Verification Checklist

After deploying, verify:

```bash
# 1. Server responds to HTTP
curl http://192.168.0.235:8080/
# Expected: HTML page (web UI)

# 2. API status endpoint works
curl http://192.168.0.235:8080/api/status
# Expected: JSON with autonomy level, node info, etc.

# 3. Server started quickly (no hang)
# Check: Time from `python3 server.py` to "Uvicorn running on"
# Expected: < 5 seconds

# 4. Routes are registered
curl http://192.168.0.235:8080/api/settings
# Expected: JSON with settings

# 5. UI loads without console errors
# Open http://192.168.0.235:8080 in browser, check developer tools
```

---

## What You'll See After Fix

### Before (Broken)
```
$ python3 server.py
[server] startup begin
[server] config loaded
[server] audit imported
[server] creating FastAPI app...
[server] startup complete
INFO:     Started server process [19524]
INFO:     Waiting for application startup.
[HANGS HERE FOR 30-60 seconds]
```

### After (Fixed)
```
$ python3 server.py
INFO:     Started server process [1234]
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
# Starts in ~2 seconds!
```

---

## Troubleshooting

### Server still says "Not Found" for `/`
**Cause:** Old code is still running
**Fix:** `pkill -f "python3 server.py"` then restart with new code

### "Module inventory has no attribute..."
**Cause:** Inventory module import failed (likely Proxmox API auth issue)
**Fix:** Check `.env` file has valid `PROXMOX_HOST`, `PROXMOX_API_TOKEN`, SSH keys path

### "No such file or directory: gui/index.html"
**Cause:** Running from wrong directory
**Fix:** `cd /home/pi/proxmox-agent` before `python3 server.py`

### Server starts but routes 404
**Cause:** FastAPI app was created but routes didn't register (syntax error)
**Fix:** Check for Python syntax errors: `python3 -m py_compile server.py`

---

## Git Commit Details

**Commit:** d482d08  
**Message:** Fix server startup hang: lazy-load heavy modules and restore main entry point  
**Date:** 2026-06-03

**Changes:**
- Removed module-level imports of inventory, tools, ProxmoxAPI, SSHClient
- Added lazy-loading functions: `_ensure_tools()`, `_ensure_inventory()`, `_get_proxmox_api()`, `_get_ssh_client()`
- Routes now import on first call, not at startup
- Restored `if __name__ == "__main__"` entry point
- Server starts in <5 seconds instead of hanging

---

## Next Steps

1. **Deploy on BananaPi** (follow Option 1 above)
2. **Test all routes** (see verification checklist)
3. **Run first inventory query** — this will trigger the first module import
4. **Confirm audit log is created** at `~/.proxmox-agent/audit.jsonl`
5. **Monitor for 24h** — verify no regressions, all tools work

---

## Questions?

- Check `README.md` for architecture & tool reference
- Review `SECURITY_LEVELS.md` for autonomy level info
- See `.env.example` for configuration template

**All code is on GitHub:** https://github.com/config-collab/proxmox-agent
