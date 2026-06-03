"""
Minimal FastAPI server to get the UI working while debugging module imports.
"""
import json
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

app = FastAPI()
GUI = Path(__file__).parent / "gui"

@app.get("/")
async def index():
    return HTMLResponse((GUI / "index.html").read_text(encoding="utf-8"))

@app.get("/assistant.css")
async def serve_css():
    return Response((GUI / "assistant.css").read_text(encoding="utf-8"), media_type="text/css")

@app.get("/assistant.js")
async def serve_js():
    return Response((GUI / "assistant.js").read_text(encoding="utf-8"), media_type="application/javascript")

@app.get("/api/status")
async def api_status():
    return {
        "node": "192.168.0.91",
        "agent": "192.168.0.235:8080",
        "provider": "claude",
        "status": "running",
        "autonomy": 1,
        "summary": {
            "inventory": {"value": "5 guests", "status": "ok", "note": "3 running"},
            "backups": {"value": "healthy", "status": "ok", "note": "0 overdue"},
            "patches": {"value": "2 pending", "status": "warn", "note": "1 security"},
            "security": {"value": "B", "status": "ok", "note": "0 critical"}
        }
    }

@app.get("/api/settings")
async def api_get_settings():
    return {
        "autonomy": 1,
        "provider": "claude",
        "providers": {
            "claude": {"label": "Claude 3.5 Sonnet", "model": "claude-3-5-sonnet-20241022", "key": "ANTHROPIC_API_KEY"}
        },
        "proxmox_host": os.environ.get("PROXMOX_HOST", "192.168.0.91"),
        "pre_change_backup": "snapshot",
        "pve_protection": "strict"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
