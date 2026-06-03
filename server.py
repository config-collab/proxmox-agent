"""
Proxmox Assistant — FastAPI web server.

Serves the GUI and streams agent tool calls over SSE.
Run:  uvicorn server:app --host 0.0.0.0 --port 8080

SSE protocol (POST /api/chat):
  event: thinking         data: {}
  event: tool_start       data: {name, sig}
  event: tool_line        data: {cls, text}
  event: tool_end         data: {name}
  event: tool_result      data: {name, kind, data, summary}
  event: ai_text          data: {html}
  event: plan_start       data: {steps}
  event: plan_step_active data: {index, name}
  event: plan_step_done   data: {index, meta, status}
  event: plan_done        data: {}
  event: error            data: {message}
  event: done             data: {}
"""
import html as _html
import json
import os
import re
import socket
import asyncio
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

# Bootstrap env before importing agent modules
import config
config._load_env()

# NOTE: Heavy modules are lazy-loaded to avoid startup hang
import audit

# Lazy-loaded on first use
_tools_mod = None
_inv_mod = None
_proxmox_api = None
_ssh_client = None

def _ensure_tools():
    global _tools_mod
    if _tools_mod is None:
        import tools as tools_mod_tmp
        _tools_mod = tools_mod_tmp
    return _tools_mod

def _ensure_inventory():
    global _inv_mod
    if _inv_mod is None:
        import inventory as inv_mod_tmp
        _inv_mod = inv_mod_tmp
    return _inv_mod

def _get_proxmox_api():
    global _proxmox_api
    if _proxmox_api is None:
        from proxmox_api import ProxmoxAPI as PA
        _proxmox_api = PA
    return _proxmox_api

def _get_ssh_client():
    global _ssh_client
    if _ssh_client is None:
        from ssh_client import SSHClient as SC
        _ssh_client = SC
    return _ssh_client

app = FastAPI()
GUI  = Path(__file__).parent / "gui"
PROFILE_PATH = Path.home() / ".proxmox-agent" / "env_profile.json"


# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return HTMLResponse((GUI / "index.html").read_text(encoding="utf-8"))

@app.get("/assistant.css")
async def serve_css():
    return Response((GUI / "assistant.css").read_text(encoding="utf-8"), media_type="text/css")

@app.get("/assistant.js")
async def serve_js():
    return Response((GUI / "assistant.js").read_text(encoding="utf-8"),
                    media_type="application/javascript")


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/prefetch/inventory")
async def api_prefetch_inventory():
    """Pre-run inventory so the result is ready before the user asks."""
    loop = asyncio.get_event_loop()
    raw, structured = await loop.run_in_executor(None, lambda: _call_tool("get_inventory", {}))
    return structured or {"kind": "inventory", "data": {}, "summary": ""}


@app.get("/api/helper-scripts")
async def api_helper_scripts(q: str = ""):
    from docs.helper_scripts import search
    results = search(q, top_k=12) if q else []
    return results


@app.post("/api/run-script")
async def api_run_script(body: dict):
    """Run a community helper script on the Proxmox host via SSH. Requires autonomy >= 2."""
    level = int(os.environ.get("AGENT_AUTONOMY", "1"))
    if level < 2:
        return {"ok": False, "error": "Blocked: raise Security level to Maintain or Full to run scripts."}
    run_cmd = body.get("run_cmd", "")
    if not run_cmd or "curl" not in run_cmd:
        return {"ok": False, "error": "Invalid script command."}
    try:
        SSH = _get_ssh_client()
        with SSH() as ssh:
            out, err, rc = ssh.run(run_cmd, check=False, timeout=300)
        audit.log("helper_script.run", run_cmd[:80], outcome="ok" if rc == 0 else f"exit {rc}", reversible=False)
        audit.flush()
        return {"ok": rc == 0, "output": (out + "\n" + err).strip()[-4000:]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/manifest.json")
async def serve_manifest():
    return Response((GUI / "manifest.json").read_text(encoding="utf-8"),
                    media_type="application/manifest+json")

@app.get("/api/audit")
async def api_audit():
    path = Path(os.path.expanduser(os.environ.get("AUDIT_LOG_PATH",
                "~/.proxmox-agent/audit.jsonl")))
    if not path.exists():
        return []
    entries = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try: entries.append(json.loads(line))
                except Exception: pass
    except Exception:
        pass
    return entries[-100:]

@app.get("/api/status")
async def api_status():
    if PROFILE_PATH.exists():
        try:
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            return _status_from_profile(profile)
        except Exception:
            pass
    return _default_status()


def _status_from_profile(p: dict) -> dict:
    items  = p.get("action_items", [])
    crits  = sum(1 for a in items if a.get("priority") == "critical")
    highs  = sum(1 for a in items if a.get("priority") == "high")
    bak    = p.get("backup_health", {})
    pat    = p.get("patch_status", {})
    sec    = p.get("security_posture", {})
    guests = p.get("guests", [])
    running = sum(1 for g in guests if g.get("status") == "running")
    total   = len(guests)
    return {
        "node":      os.environ.get("PROXMOX_HOST", "?"),
        "pbs":       os.environ.get("PBS_HOST", ""),
        "agent":     f"{_local_ip()}:8080",
        "provider":  os.environ.get("LLM_PROVIDER", "claude"),
        "generated": p.get("profile_date", ""),
        "summary": {
            "inventory": {
                "value":  f"{total} guests",
                "status": "ok" if running == total else "warn",
                "note":   f"{running} running",
            },
            "backups": {
                "value":  bak.get("coverage", "?"),
                "status": "ok" if bak.get("overdue_count", 1) == 0 else "warn",
                "note":   f"{bak.get('overdue_count', 0)} overdue",
            },
            "patches": {
                "value":  f"{pat.get('total_pending', '?')} pending",
                "status": "ok" if pat.get("total_pending", 1) == 0 else "warn",
                "note":   f"{pat.get('security_count', 0)} security",
            },
            "security": {
                "value":  sec.get("score", "?"),
                "status": "bad" if crits > 0 else ("warn" if highs > 0 else "ok"),
                "note":   f"{crits} critical" if crits else f"{highs} high",
            },
        },
    }


def _default_status() -> dict:
    return {
        "node":      os.environ.get("PROXMOX_HOST", "?"),
        "pbs":       os.environ.get("PBS_HOST", ""),
        "agent":     f"{_local_ip()}:8080",
        "provider":  os.environ.get("LLM_PROVIDER", "claude"),
        "generated": "",
        "autonomy":  int(os.environ.get("AGENT_AUTONOMY", "1")),
        "summary": {
            k: {"value": "—", "status": "warn", "note": "not scanned yet"}
            for k in ("inventory", "backups", "patches", "security")
        },
    }


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def api_get_settings():
    def mask(k: str) -> str:
        v = os.environ.get(k, "")
        return (v[:4] + "••••" + v[-3:]) if len(v) >= 8 else ("set" if v else "")

    return {
        "provider":     os.environ.get("LLM_PROVIDER", "claude"),
        "proxmox_host": os.environ.get("PROXMOX_HOST", ""),
        "ssh_user":     os.environ.get("SSH_USER", "root"),
        "pbs_host":     os.environ.get("PBS_HOST", ""),
        "agent":        f"{_local_ip()}:8080",
        "autonomy":          int(os.environ.get("AGENT_AUTONOMY", "1")),
        "pre_change_backup": os.environ.get("PRE_CHANGE_BACKUP", "snapshot"),
        "pve_protection":    os.environ.get("PVE_PROTECTION_MODE", "strict"),
        "ntfy_url":          os.environ.get("NTFY_URL", ""),
        "providers": {
            "claude": {
                "label": "Claude", "model": "claude-sonnet-4-6", "kind": "cloud",
                "key": "ANTHROPIC_API_KEY", "masked": mask("ANTHROPIC_API_KEY"),
            },
            "openai": {
                "label": "OpenAI", "model": "gpt-4o", "kind": "cloud",
                "key": "OPENAI_API_KEY", "masked": mask("OPENAI_API_KEY"),
            },
            "ollama": {
                "label": "Ollama", "model": "llama3:8b", "kind": "local",
                "key": "OLLAMA_HOST",
                "masked": os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1"),
            },
        },
    }


class SettingsPayload(BaseModel):
    provider:      str = ""
    proxmox_host:  str = ""
    proxmox_token: str = ""
    proxmox_pass:  str = ""
    ssh_user:      str = ""
    pbs_host:      str = ""
    ntfy_url:          str = ""
    autonomy:          int = -1
    pre_change_backup: str = ""
    pve_protection:    str = ""
    api_key:           str = ""


@app.post("/api/settings")
async def api_save_settings(body: SettingsPayload):
    env_path = Path(__file__).parent / ".env"
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""

    updates: dict[str, str] = {}
    if body.provider:        updates["LLM_PROVIDER"]      = body.provider
    if body.proxmox_host:    updates["PROXMOX_HOST"]      = body.proxmox_host
    if body.proxmox_token:   updates["PROXMOX_API_TOKEN"] = body.proxmox_token
    if body.proxmox_pass:    updates["PROXMOX_PASS"]      = body.proxmox_pass
    if body.ssh_user:        updates["SSH_USER"]           = body.ssh_user
    if body.ntfy_url:                       updates["NTFY_URL"]            = body.ntfy_url
    if body.autonomy >= 0:                  updates["AGENT_AUTONOMY"]      = str(body.autonomy)
    if body.pre_change_backup in ("none","snapshot","pbs"):
                                            updates["PRE_CHANGE_BACKUP"]   = body.pre_change_backup
    if body.pve_protection in ("strict","warn","off"):
                                            updates["PVE_PROTECTION_MODE"] = body.pve_protection
    if body.pbs_host:     updates["PBS_HOST"]       = body.pbs_host
    if body.api_key:
        key_map = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                   "ollama": "OPENAI_BASE_URL"}
        k = key_map.get(body.provider)
        if k:
            updates[k] = body.api_key

    lines, done = [], set()
    for line in text.splitlines():
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            k = stripped.split("=", 1)[0]
            if k in updates:
                lines.append(f"{k}={updates[k]}")
                done.add(k); continue
        lines.append(line)
    for k, v in updates.items():
        if k not in done:
            lines.append(f"{k}={v}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Update live env (setdefault won't override, so set directly)
    for k, v in updates.items():
        os.environ[k] = v

    return {"ok": True}


# ── Chat SSE ──────────────────────────────────────────────────────────────────

class ChatPayload(BaseModel):
    message: str


@app.post("/api/chat")
async def api_chat(body: ChatPayload):
    return StreamingResponse(
        _chat_stream(body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# Intent routing — mirrors frontend classify()
_INTENT_PATTERNS = [
    (r"full|health.?check|check.?up|everything|status.report|rundown|sweep|look.around", "checkup"),
    (r"patch|updat|upgrad|apt|cve|package",                                              "patches"),
    (r"backup|pbs|snapshot|restore|datastore|vzdump",                                    "backups"),
    (r"inventory|running|vm|guest|what.?s.up|cluster|list.*(vm|container|lxc)",          "inventory"),
    (r"secur|audit|harden|vuln|firewall|ssh.*(config|key)|tls|cert|2fa",                 "security"),
    (r"install|script|helper|community|lxc.*(creat|new)|container.*(new|creat|add)",     "helpers"),
]


def _classify(msg: str) -> str:
    m = msg.lower()
    for pattern, intent in _INTENT_PATTERNS:
        if re.search(pattern, m):
            return intent
    return "fallback"


# Progress lines shown in the tool log before the real call completes
_PROGRESS: dict[str, list[str]] = {
    "get_inventory":  ["› pvesh get /cluster/resources --type vm,lxc"],
    "check_patches":  ["› apt-get update -q", "› apt list --upgradable"],
    "apply_patches":  ["› apt-get install --only-upgrade ..."],
    "check_backups":  ["› reading vzdump job configs + backup archives"],
    "check_pbs":      ["› proxmox-backup-manager datastore status",
                       "› proxmox-backup-manager task list"],
    "security_audit": ["› sshd_config · pve-firewall · realm 2fa · open ports"],
    "search_docs":            ["› searching local BM25 corpus"],
    "search_forum":           ["› querying forum.proxmox.com/search.json"],
    "search_helper_scripts":  ["› fetching community-scripts/ProxmoxVE (cached 24h)"],
}


async def _chat_stream(message: str) -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()
    yield _sse("thinking", {})

    intent = _classify(message)

    try:
        if intent == "checkup":
            async for ev in _stream_checkup(loop):
                yield ev
        elif intent == "inventory":
            async for ev in _stream_one_tool(loop, "get_inventory", {}, message):
                yield ev
            yield _sse("done", {})
        elif intent == "patches":
            async for ev in _stream_one_tool(loop, "check_patches", {}, message):
                yield ev
            yield _sse("done", {})
        elif intent == "backups":
            async for ev in _stream_one_tool(loop, "check_backups", {}, ""):
                yield ev
            async for ev in _stream_one_tool(loop, "check_pbs", {}, message):
                yield ev
            yield _sse("done", {})
        elif intent == "security":
            async for ev in _stream_one_tool(loop, "security_audit", {"host_only": True}, message):
                yield ev
            yield _sse("done", {})
        elif intent == "helpers":
            # Extract the search query: strip intent keywords, use remainder
            query = re.sub(r'\b(install|script|helper|community|container|lxc|create|new|add)\b', '', message, flags=re.I).strip() or message
            async for ev in _stream_one_tool(loop, "search_helper_scripts", {"query": query}, message):
                yield ev
            yield _sse("done", {})
        else:
            async for ev in _stream_llm_loop(loop, message):
                yield ev
    except Exception as exc:
        yield _sse("error", {"message": str(exc)})
        yield _sse("done", {})


async def _stream_one_tool(
    loop: asyncio.AbstractEventLoop,
    name: str,
    inputs: dict,
    user_msg: str,
) -> AsyncGenerator[str, None]:
    yield _sse("tool_start", {"name": name, "sig": _sig(name, inputs)})
    for line in _PROGRESS.get(name, []):
        yield _sse("tool_line", {"cls": "mut", "text": line})
        await asyncio.sleep(0)

    blocked = _autonomy_gate(name)
    if blocked:
        yield _sse("tool_end", {"name": name})
        yield _sse("blocked", {"message": blocked})
        return

    # Pre-flight checks for apply_patches
    if name == "apply_patches":
        guest = inputs.get("guest_name", "")
        # 1. LLM-as-judge: safety assessment with extended thinking
        patch_list = []
        try:
            _raw_check, _structured_check = await loop.run_in_executor(
                None, lambda: _call_tool("check_patches", {"guest_name": guest} if guest else {})
            )
            patch_list = _structured_check.get("data", {}).get("list", []) if _structured_check else []
        except Exception:
            pass
        if patch_list and os.environ.get("LLM_PROVIDER"):
            yield _sse("tool_line", {"cls": "mut", "text": f"Assessing {len(patch_list)} packages with extended reasoning..."})
            score, verdict, concerns = await _judge_patch_safety(loop, patch_list)
            cls = "ok" if score >= 4 else ("mut" if score == 3 else "bad")
            yield _sse("tool_line", {"cls": cls, "text": f"Safety {score}/5: {verdict}"})
            for c in concerns:
                yield _sse("tool_line", {"cls": "mut", "text": f"  ! {c}"})
            yield _sse("judge_result", {"score": score, "verdict": verdict, "concerns": concerns})
            if score <= 2 and int(os.environ.get("AGENT_AUTONOMY", "1")) < 3:
                yield _sse("blocked", {"message": f"Patches rated unsafe ({score}/5): {verdict}. Set autonomy=Full to override."})
                yield _sse("done", {})
                return
        # 2. Snapshot before writing
        if guest:
            yield _sse("tool_line", {"cls": "mut", "text": f"Taking pre-patch snapshot of {guest}..."})
            snap, err = await _snapshot_guest(loop, guest)
            if snap:
                yield _sse("tool_line", {"cls": "ok", "text": f"Snapshot '{snap}' ready — safe to proceed"})
            else:
                yield _sse("tool_line", {"cls": "mut", "text": f"Snapshot skipped: {err}"})

    raw, structured = await loop.run_in_executor(None, lambda: _call_tool(name, inputs))

    ok_summary = structured.get("summary", "done") if structured else "done"
    yield _sse("tool_line", {"cls": "ok", "text": f"✓ {ok_summary}"})
    yield _sse("tool_end", {"name": name})

    if structured:
        yield _sse("tool_result", {
            "name":    name,
            "kind":    structured["kind"],
            "data":    structured["data"],
            "summary": structured.get("summary", ""),
        })

    if user_msg and os.environ.get("LLM_PROVIDER") and os.environ.get("ANTHROPIC_API_KEY",
                                                                        os.environ.get("OPENAI_API_KEY", "")):
        comment = await loop.run_in_executor(None, lambda: _quick_comment(user_msg, raw[:1500]))
        if comment:
            yield _sse("ai_text", {"html": _md_html(comment)})


async def _stream_checkup(loop: asyncio.AbstractEventLoop) -> AsyncGenerator[str, None]:
    """Run all 4 checkup tools in parallel — results stream as they complete."""
    steps = ["get_inventory", "check_patches", "check_backups", "security_audit"]
    inputs_map = {"security_audit": {"host_only": True}}

    yield _sse("plan_start", {"steps": steps})
    # Activate all steps simultaneously to show parallel execution
    for i, name in enumerate(steps):
        yield _sse("plan_step_active", {"index": i, "name": name})
    await asyncio.sleep(0)

    async def _run_one(i: int, name: str):
        inp = inputs_map.get(name, {})
        raw, structured = await loop.run_in_executor(None, lambda n=name, x=inp: _call_tool(n, x))
        return i, name, raw, structured

    results: dict[str, dict] = {}
    tasks = [asyncio.ensure_future(_run_one(i, n)) for i, n in enumerate(steps)]

    for coro in asyncio.as_completed(tasks):
        i, name, raw, structured = await coro

        ok_summary = structured.get("summary", "done") if structured else "done"

        if structured:
            yield _sse("tool_result", {
                "name":    name,
                "kind":    structured["kind"],
                "data":    structured["data"],
                "summary": structured.get("summary", ""),
            })
            results[name] = structured

        step_status = "ok"
        if structured:
            d = structured.get("data", {})
            if name == "check_patches" and d.get("total", 0) > 0:
                step_status = "warn"
            elif name == "check_backups":
                step_status = "warn"
            elif name == "security_audit":
                crits = sum(1 for f in d.get("findings", []) if f.get("sev") == "critical")
                step_status = "bad" if crits else ("warn" if d.get("findings") else "ok")

        yield _sse("plan_step_done", {"index": i, "meta": ok_summary, "status": step_status})

    yield _sse("plan_done", {})

    if os.environ.get("LLM_PROVIDER") and os.environ.get("ANTHROPIC_API_KEY",
                                                           os.environ.get("OPENAI_API_KEY", "")):
        summary_ctx = "; ".join(r.get("summary", "") for r in results.values() if r.get("summary"))
        comment = await loop.run_in_executor(
            None, lambda: _quick_comment("full health check of the cluster", summary_ctx)
        )
        if comment:
            yield _sse("ai_text", {"html": _md_html(comment)})

    yield _sse("done", {})


async def _stream_llm_loop(
    loop: asyncio.AbstractEventLoop, message: str
) -> AsyncGenerator[str, None]:
    """Fallback: full LLM agentic tool-calling loop."""
    try:
        import llm as llm_mod
    except ImportError:
        yield _sse("ai_text", {"html": "LLM not configured — set LLM_PROVIDER + API key in settings."})
        yield _sse("done", {})
        return

    ctx = ""
    if PROFILE_PATH.exists():
        try:
            from onboarding import profile_to_context
            ctx = profile_to_context(json.loads(PROFILE_PATH.read_text()))
        except Exception:
            pass

    system = (
        "You are a Proxmox homelab assistant running on a BananaPi. "
        "Use tools to answer. Be concise — 1-2 sentences after tool results."
        + (f" Environment: {ctx}" if ctx else "")
    )
    msgs = [{"role": "user", "content": f"[system]{system}[/system]\n\n{message}",
             "_system_seed": True}]
    tools = _ensure_tools()
    schemas = tools.all_schemas()

    for _ in range(6):
        text, tool_calls = await loop.run_in_executor(None, lambda: llm_mod.chat(msgs, schemas))
        if text:
            yield _sse("ai_text", {"html": _md_html(text)})
        if not tool_calls:
            break
        msgs.append(llm_mod.assistant_tool_call_message(tool_calls))
        for tc in tool_calls:
            name   = tc["name"]
            inputs = tc.get("inputs", {})
            yield _sse("tool_start", {"name": name, "sig": _sig(name, inputs)})
            for line in _PROGRESS.get(name, []):
                yield _sse("tool_line", {"cls": "mut", "text": line})
                await asyncio.sleep(0)
            raw, structured = await loop.run_in_executor(
                None, lambda n=name, i=inputs: _call_tool(n, i)
            )
            summary = structured.get("summary", "done") if structured else "done"
            yield _sse("tool_line", {"cls": "ok", "text": f"✓ {summary}"})
            yield _sse("tool_end", {"name": name})
            if structured:
                yield _sse("tool_result", {
                    "name": name, "kind": structured["kind"],
                    "data": structured["data"], "summary": summary,
                })
            msgs.append(llm_mod.tool_result_message(tc.get("id", name), raw))

    yield _sse("done", {})


# ── Tool runners ──────────────────────────────────────────────────────────────

def _sig(name: str, inputs: dict) -> str:
    if not inputs:
        return f"{name}()"
    args = ", ".join(f'{k}="{v}"' for k, v in inputs.items()
                     if v not in (None, "", False))
    return f"{name}({args})" if args else f"{name}()"


_WRITE_TOOLS = {"apply_patches"}


async def _protect_before_change(
    loop: asyncio.AbstractEventLoop, guest_name: str, node: str = "pve"
) -> tuple[str | None, str | None]:
    """
    Create a pre-change protection based on PRE_CHANGE_BACKUP setting:
      none     → skip
      snapshot → instant VM snapshot (default)
      pbs      → PBS incremental backup via vzdump API
    Returns (description, None) on success or (None, error_str) on failure.
    """
    mode = os.environ.get("PRE_CHANGE_BACKUP", "snapshot").lower()
    if mode == "none":
        return None, "disabled"

    import datetime
    label = f"pre-patch-{datetime.datetime.now().strftime('%Y%m%d-%H%M')}"

    def _find_guest():
        PVE = _get_proxmox_api()
        api = PVE(); api.login()
        for gtype, list_fn in [("qemu", api.vms), ("lxc", api.containers)]:
            guests = list_fn(node)
            target = next((g for g in guests if g.get("name") == guest_name), None)
            if target:
                return api, gtype, target["vmid"], target
        return None, None, None, None

    if mode == "snapshot":
        def _do():
            api, gtype, vmid, _ = _find_guest()
            if not api:
                return None, f"guest '{guest_name}' not found"
            try:
                api.post(f"/nodes/{node}/{gtype}/{vmid}/snapshot", {
                    "snapname": label,
                    "description": "pre-patch auto snapshot by proxmox-agent",
                })
                return f"snapshot '{label}'", None
            except Exception as exc:
                return None, str(exc)
        return await loop.run_in_executor(None, _do)

    if mode == "pbs":
        def _do_pbs():
            api, gtype, vmid, _ = _find_guest()
            if not api:
                return None, f"guest '{guest_name}' not found"
            try:
                storage = os.environ.get("BACKUP_STORAGE", "local-pbs")
                task = api.post(f"/nodes/{node}/vzdump", {
                    "vmid":     str(vmid),
                    "mode":     "snapshot",
                    "compress": "zstd",
                    "storage":  storage,
                    "notes-template": f"auto pre-patch {label}",
                })
                # task is a UPID string; poll until done (max 10 min)
                import time
                upid = task if isinstance(task, str) else str(task)
                for _ in range(120):
                    time.sleep(5)
                    try:
                        status = api.get(f"/nodes/{node}/tasks/{upid.replace(':', '%3A', 1).replace(':', '%3A', 1)}/status")
                        if status.get("status") == "stopped":
                            ok = status.get("exitstatus") == "OK"
                            return (f"PBS backup completed ({storage})", None) if ok else (None, f"PBS backup failed: {status.get('exitstatus')}")
                    except Exception:
                        pass
                return f"PBS backup started (UPID: {upid[:20]}…)", None
            except Exception as exc:
                return None, str(exc)
        return await loop.run_in_executor(None, _do_pbs)

    return None, f"unknown PRE_CHANGE_BACKUP mode: {mode}"


# Keep old name as alias
_snapshot_guest = _protect_before_change

def _autonomy_gate(name: str) -> str | None:
    """Return a blocked message if current autonomy level forbids this tool, else None."""
    level = int(os.environ.get("AGENT_AUTONOMY", "1"))
    if level == 0 and name in _WRITE_TOOLS:
        return (f"Blocked: agent is in Observe mode (read-only). "
                f"Open Settings and raise the Security level to allow writes.")
    return None


def _call_tool(name: str, inputs: dict) -> tuple[str, dict | None]:
    """
    Run a tool and return (markdown_for_llm, structured_dict_for_ui | None).
    Calls underlying module functions directly to get both in one pass.
    """
    blocked = _autonomy_gate(name)
    if blocked:
        return blocked, None
    if name == "get_inventory":
        return _run_inventory(inputs)
    if name == "check_patches":
        return _run_patches(inputs)
    if name == "security_audit":
        return _run_security(inputs)
    if name == "get_metrics":
        tools = _ensure_tools()
        raw = tools.dispatch(name, inputs)
        return raw, {"kind": "metrics", "data": {"raw": raw, "name": inputs.get("name",""), "timeframe": inputs.get("timeframe","hour")}, "summary": f"metrics for {inputs.get('name','')}"}

    if name == "search_helper_scripts":
        from docs.helper_scripts import search as hs_search
        query  = inputs.get("query", "")
        top_k  = int(inputs.get("top_k", 6))
        scripts = hs_search(query, top_k)
        tools = _ensure_tools()
        raw    = tools.dispatch(name, inputs)
        return raw, {
            "kind": "helpers",
            "data": {"scripts": scripts, "query": query},
            "summary": f"{len(scripts)} scripts found for '{query}'",
        }
    # check_backups / check_pbs / search_* — dispatch returns markdown, wrap as raw
    tools = _ensure_tools()
    raw = tools.dispatch(name, inputs)
    kind = {"check_backups": "backups", "check_pbs": "pbs"}.get(name)
    if kind:
        return raw, {"kind": kind, "data": {"raw": raw}, "summary": ""}
    return raw, None


def _run_inventory(inputs: dict) -> tuple[str, dict]:
    node = inputs.get("node", "pve")
    PVE = _get_proxmox_api()
    api = PVE(); api.login()
    SSH = _get_ssh_client()
    with SSH() as ssh:
        inventory = _ensure_inventory()
        snap = inventory.collect(api, ssh, node=node)
    inventory = _ensure_inventory()
    raw = inventory.render(snap)
    audit.log("inventory.collect", node, outcome="ok", reversible=True)
    conns = config.guest_connections()
    guests = []
    for g in snap.guests:
        if g.maxmem_mb >= 1024:
            mem = f"{g.maxmem_mb/1024:.1f}G"
        elif g.maxmem_mb:
            mem = f"{g.maxmem_mb}M"
        else:
            mem = "—"
        conn = conns.get(g.name, {})
        guests.append({
            "id":    g.id,
            "name":  g.name,
            "node":  node,
            "state": g.status,
            "cpu":   f"{g.cpus}c" if g.cpus else "—",
            "mem":   mem,
            "load":  "—",
            "ip":    conn.get("ip", ""),
        })
    running = sum(1 for g in guests if g["state"] == "running")
    return raw, {
        "kind": "inventory",
        "data": {"guests": guests, "total": len(guests), "running": running},
        "summary": f"{len(guests)} guests · {running} running",
    }


def _run_patches(inputs: dict) -> tuple[str, dict]:
    from tools.patch_tool import check_patches
    raw = check_patches(**{k: v for k, v in inputs.items() if k == "guest_name"})
    pkgs = _parse_patch_list(raw)
    sec  = sum(1 for p in pkgs if p["type"] == "security")
    ker  = sum(1 for p in pkgs if p["type"] == "kernel")
    return raw, {
        "kind": "patches",
        "data": {"host": "pve", "total": len(pkgs), "security": sec, "kernel": ker, "list": pkgs[:20]},
        "summary": f"{len(pkgs)} pending · {sec} security" if pkgs else "all up to date",
    }


def _run_security(inputs: dict) -> tuple[str, dict]:
    from tools.security_tool import security_audit
    raw = security_audit(**{k: v for k, v in inputs.items()
                            if k in ("guest_name", "host_only")})
    findings = _parse_findings(raw)
    crits    = sum(1 for f in findings if f["sev"] == "critical")
    highs    = sum(1 for f in findings if f["sev"] == "high")
    score    = "A" if crits == 0 and highs == 0 else ("B+" if crits == 0 else "B")
    return raw, {
        "kind": "security",
        "data": {"score": score, "findings": findings},
        "summary": f"{len(findings)} findings · {crits} critical",
    }


def _parse_patch_list(md: str) -> list[dict]:
    """
    Parse patch report markdown table:
      | `package` | category | available |
    """
    pkgs = []
    for line in md.splitlines():
        m = re.match(r"\|\s*`?([^`|]+?)`?\s*\|\s*(security|kernel|routine)\s*\|\s*([^|]+?)\s*\|",
                     line.strip(), re.IGNORECASE)
        if m:
            pkgs.append({
                "pkg":  m.group(1).strip(),
                "to":   m.group(3).strip() or "—",
                "type": m.group(2).lower(),
            })
    return pkgs


def _parse_findings(md: str) -> list[dict]:
    """
    Parse security audit markdown:
      ### [CRITICAL]
      **target / category** — title
        > detail
    """
    findings = []
    sev_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "INFO": "low"}
    glyph   = {"critical": "▲", "high": "●", "medium": "◆", "low": "○"}
    current_sev = None
    cur = None
    for line in md.splitlines():
        line = line.strip()
        # Section header: ### [CRITICAL]
        m_sec = re.match(r"###\s*\[(\w+)\]", line)
        if m_sec:
            sk = m_sec.group(1)
            current_sev = sev_map.get(sk)
            cur = None
            continue
        if not current_sev:
            continue
        # Finding line: **target / category** — title
        m_find = re.match(r"\*\*(.+?)\*\*\s*[—–-]\s*(.+)", line)
        if m_find:
            cur = {
                "sev":    current_sev,
                "glyph":  glyph[current_sev],
                "title":  m_find.group(2).strip()[:80],
                "where":  m_find.group(1).strip()[:60],
                "detail": "",
            }
            findings.append(cur)
        elif cur and line.startswith("> "):
            cur["detail"] = line[2:].strip()[:150]
    return findings


async def _judge_patch_safety(
    loop: asyncio.AbstractEventLoop, packages: list[dict]
) -> tuple[int, str, list[str]]:
    """
    Ask the LLM (with extended thinking if Claude) to assess patch safety.
    Returns (score 1-5, verdict, concerns[]).  5=safe, 1=risky.
    Falls back to (3, "unknown", []) if LLM not available.
    """
    if not os.environ.get("LLM_PROVIDER"):
        return 3, "LLM not configured", []
    pkg_list = ", ".join(f"{p['pkg']} -> {p['to']}" for p in packages[:15])
    prompt = (
        f"Assess these Proxmox package upgrades for safety:\n{pkg_list}\n\n"
        "Rate safety 1-5 (5=safe, 1=risky). Check for: kernel updates needing reboot, "
        "known breaking changes in pve-manager/pve-kernel, CVE fixes, dependencies. "
        'Respond ONLY as JSON: {"score": N, "verdict": "short sentence", "concerns": ["..."]}'
    )
    try:
        import llm as llm_mod
        msgs = [{"role": "user", "content": prompt}]
        # Use extended thinking for better analysis (Claude only, graceful fallback)
        text, _ = await loop.run_in_executor(
            None, lambda: llm_mod.chat(msgs, [], thinking_budget=6000)
        )
        if text:
            m = re.search(r'\{[^{}]+\}', text, re.DOTALL)
            if m:
                d = json.loads(m.group())
                return int(d.get("score", 3)), d.get("verdict", ""), d.get("concerns", [])
    except Exception:
        pass
    return 3, "Could not assess", []


def _quick_comment(user_msg: str, context: str) -> str:
    """
    One-shot LLM call for a 1-2 sentence plain-English summary.
    Returns empty string if LLM is not configured or call fails.
    """
    if not os.environ.get("LLM_PROVIDER"):
        return ""
    try:
        import llm as llm_mod
        msgs = [{"role": "user", "content":
                 f"User asked: {user_msg}\n"
                 f"Tool result summary: {context}\n"
                 "Give a 1-2 sentence plain-English summary for a homelab admin. "
                 "Be direct and mention the most important item if there is one."}]
        text, _ = llm_mod.chat(msgs, [])
        return text or ""
    except Exception:
        return ""


def _md_html(text: str) -> str:
    """Minimal markdown → safe HTML for inline AI text."""
    text = _html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`",       r'<span class="em">\1</span>', text)
    return text


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
